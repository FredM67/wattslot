"""Banc d'essai de l'assistant : les questions de la suite de test posées à des modèles locaux.

Le script joue le rôle d'Open WebUI, sans interface : il lit les outils du serveur MCP de WattSlot
(``/mcp``) et le prompt conseillé (``/api/assistant/prompt``), puis pose chaque question à chaque
modèle d'Ollama (``/api/chat``) et fait les appels d'outils demandés, jusqu'à la réponse. Chaque
question est posée plusieurs fois (``--runs``) : ces petits modèles ne répondent pas toujours de
la même façon, une seule réponse ne suffit pas pour conclure.

Pour chaque tour, il enregistre les outils appelés et leurs arguments, la réponse, la longueur de
la réflexion et les durées, et relève les défauts visibles sans relire le fond : aucun outil
appelé, nom d'outil ou de champ cité, marqueur de modèle (``<channel|>``), date au format brut,
caractères chinois, réponse vide. Le fond (chiffres, sens) reste à juger en lisant le rapport.

**Aucune demande n'est déposée** : un appel de ``request_device`` avec ``confirm`` n'est pas
transmis à WattSlot (``--allow-requests`` pour le transmettre), il est relevé comme un défaut,
puisque dans la suite l'utilisateur répond toujours « non ».

Les réponses citent les équipements de la maison : le rapport (JSON Lines, une ligne par tour, et
un résumé en Markdown) est écrit dans ``dev/tools/.bench/``, ignoré par git.

Depuis la racine du dépôt (adresses de l'application et d'Ollama en argument ou dans
``WATTSLOT_URL`` et ``OLLAMA_URL``) :

    python dev/tools/assistant_bench.py --wattslot http://192.0.2.10:8100
        --ollama http://192.0.2.20:11434 [--models qwen3,lfm3] [--questions 6,12,17]
        [--runs 3] [--profiles dev/tools/assistant_bench_models.json]

Les profils de modèles (étiquette Ollama, réflexion, options) sont dans
``assistant_bench_models.json`` : les mêmes réglages que les modèles d'Open WebUI.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
PROFILES = HERE / "assistant_bench_models.json"
OUT = HERE / ".bench"
MAX_STEPS = 6  # appels d'outils enchaînés au plus avant de renoncer
TIMEOUT = 600.0  # une réponse avec réflexion peut prendre plusieurs minutes


@dataclass(frozen=True)
class Turn:
    text: str
    question: int | None = None  # numéro dans la suite ; aucun : réponse de l'utilisateur
    tools: frozenset[str] = frozenset()  # outils attendus (l'un d'eux) ; vide : aucun exigé


@dataclass(frozen=True)
class Scenario:
    key: str
    turns: tuple[Turn, ...]


def _q(number: int, text: str, *tools: str) -> Turn:
    return Turn(text=text, question=number, tools=frozenset(tools))


# La suite de 18 questions du comparatif : une conversation par scénario.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario("1", (_q(1, "Qu'est-ce qui est prévu aujourd'hui ?", "get_day_plan"),)),
    Scenario("2", (_q(2, "Combien va coûter la journée ?", "get_day_plan"),)),
    Scenario("3", (_q(3, "Quel est le prochain appareil à démarrer ?", "get_day_plan"),)),
    Scenario("4", (_q(4, "Pourquoi le chauffe-eau tourne à cette heure-là ?", "explain_device"),)),
    Scenario(
        "5",
        (
            _q(
                5,
                "Quel temps fera-t-il demain, et combien de solaire ?",
                "get_forecast",
                "get_week",
            ),
        ),
    ),
    Scenario("6", (_q(6, "Et pour le reste de la semaine ?", "get_week"),)),
    Scenario("7", (_q(7, "Combien la maison a-t-elle consommé aujourd'hui ?", "get_energy"),)),
    Scenario("8", (_q(8, "Combien j'ai produit hier ?", "get_energy"),)),
    Scenario("9", (_q(9, "Où en est la batterie en ce moment ?", "get_current_status"),)),
    Scenario("10", (_q(10, "Quand sont les heures creuses demain ?", "get_tariff"),)),
    Scenario("11", (_q(11, "Quels équipements as-tu dans la maison ?", "get_home"),)),
    Scenario("12", (_q(12, "Est-ce que quelque chose ne marche pas ?", "get_problems"),)),
    Scenario(
        "13-15",
        (
            _q(13, "Pourquoi le chauffe eau tourne à cette heure ?", "explain_device"),
            _q(14, "Et demain ?", "explain_device", "get_day_plan"),
            _q(15, "Et l'autre appareil ?"),
        ),
    ),
    Scenario(
        "16",
        (
            _q(
                16,
                "Fais tourner le lave-vaisselle au meilleur moment avant demain soir.",
                "request_device",
            ),
            Turn("non"),
            Turn("Quelles sont les demandes en cours ?", tools=frozenset({"get_requests"})),
        ),
    ),
    Scenario(
        "17",
        (_q(17, "Quelle sera la production solaire dans 10 jours ?", "get_week", "get_forecast"),),
    ),
    Scenario("18", (_q(18, "Quel est le prix du kWh ?", "get_tariff"),)),
)

# Défauts visibles dans une réponse (le fond se juge à la lecture).
LEAKS: dict[str, re.Pattern[str]] = {
    "marqueur": re.compile(r"<\|?channel\|?>|<\|[a-z_\"]+\|?>|</?think>"),
    "nom technique": re.compile(r"\b[a-z]+(?:_[a-z]+)+\b"),  # get_week, latest_date…
    "date brute": re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    "chinois": re.compile(r"[一-鿿]"),
}


def post_json(url: str, body: Any, timeout: float = TIMEOUT) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode())


class Mcp:
    """Client minimal du serveur MCP de WattSlot (sans état, réponses JSON)."""

    def __init__(self, url: str, post: Callable[[str, Any], Any] = post_json) -> None:
        self.url = url
        self.post = post
        self.ids = 0

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        self.ids += 1
        found = self.post(
            self.url, {"jsonrpc": "2.0", "id": self.ids, "method": method, "params": params}
        )
        if "error" in found:
            raise RuntimeError(f"MCP {method} : {found['error']}")
        return found["result"]

    def tools(self) -> list[dict[str, Any]]:
        return list(self._rpc("tools/list", {})["tools"])

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("structuredContent") is not None:
            return json.dumps(result["structuredContent"], ensure_ascii=False)
        return "\n".join(c.get("text", "") for c in result.get("content", []))


def ollama_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Outils MCP au format d'Ollama (celui des fonctions d'OpenAI)."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


@dataclass
class Step:
    """Un appel d'outil fait pendant un tour."""

    name: str
    arguments: dict[str, Any]
    forwarded: bool = True


@dataclass
class TurnResult:
    scenario: str
    run: int
    model: str
    turn: int
    question: int | None
    text: str
    answer: str = ""
    steps: list[Step] = field(default_factory=list)
    thinking_chars: int = 0
    wall_s: float = 0.0
    ollama_s: float = 0.0
    eval_count: int = 0
    error: str | None = None
    flags: list[str] = field(default_factory=list)
    verdict: str = ""


def flags_of(result: TurnResult, expected: frozenset[str]) -> list[str]:
    """Défauts visibles d'un tour ; ceux qui rendent la réponse fausse viennent en tête."""
    found: list[str] = []
    called = {s.name for s in result.steps}
    if result.error:
        found.append(f"erreur : {result.error}")
    if not result.answer.strip():
        found.append("réponse vide")
    if expected and not called & expected:
        found.append("aucun outil attendu" if not called else "autre outil")
    if any(not s.forwarded for s in result.steps):
        found.append("demande confirmée sans accord")
    for label, pattern in LEAKS.items():
        if pattern.search(result.answer):
            found.append(label)
    return found


SERIOUS = ("erreur", "réponse vide", "aucun outil attendu", "demande confirmée sans accord")


def verdict_of(flags: list[str]) -> str:
    """Pastille provisoire : rouge pour une réponse manquante ou dangereuse, orange pour un défaut
    de forme, verte sinon ; le fond reste à vérifier à la lecture."""
    if any(f.startswith(SERIOUS) for f in flags):
        return "ko"
    return "mid" if flags else "ok"


@dataclass(frozen=True)
class Profile:
    name: str
    model: str
    think: bool | None = None
    options: dict[str, Any] = field(default_factory=dict)


def load_profiles(path: Path) -> dict[str, Profile]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: Profile(
            name=name,
            model=spec["model"],
            think=spec.get("think"),
            options=spec.get("options", {}),
        )
        for name, spec in raw.items()
        if not name.startswith("_")
    }


class Bench:
    def __init__(
        self,
        ollama: str,
        mcp: Mcp,
        prompt: str,
        allow_requests: bool = False,
        post: Callable[[str, Any], Any] = post_json,
    ) -> None:
        self.chat_url = ollama.rstrip("/") + "/api/chat"
        self.mcp = mcp
        self.prompt = prompt
        self.allow_requests = allow_requests
        self.post = post
        self.tools = ollama_tools(mcp.tools())

    def _chat(self, profile: Profile, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": profile.model,
            "messages": messages,
            "tools": self.tools,
            "stream": False,
            "options": profile.options,
            "keep_alive": "30m",
        }
        if profile.think is not None:
            body["think"] = profile.think
        found: dict[str, Any] = self.post(self.chat_url, body)
        return found

    def _tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Résultat d'un appel d'outil, et s'il a été transmis à WattSlot."""
        if name == "request_device" and arguments.get("confirm") and not self.allow_requests:
            return (
                json.dumps({"filed": False, "note": "Not filed (assistant bench)."}),
                False,
            )
        try:
            return self.mcp.call(name, arguments), True
        except Exception as error:  # noqa: BLE001 — l'erreur est rendue au modèle, comme HA
            return json.dumps({"error": str(error)}), True

    def turn(self, profile: Profile, messages: list[dict[str, Any]], result: TurnResult) -> None:
        """Un tour : la question, les appels d'outils demandés, jusqu'à la réponse."""
        start = time.monotonic()
        messages.append({"role": "user", "content": result.text})
        try:
            for _ in range(MAX_STEPS):
                reply = self._chat(profile, messages)
                message = reply.get("message", {})
                result.ollama_s += reply.get("total_duration", 0) / 1e9
                result.eval_count += reply.get("eval_count", 0)
                result.thinking_chars += len(message.get("thinking") or "")
                calls = message.get("tool_calls") or []
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.get("content", ""),
                        **({"tool_calls": calls} if calls else {}),
                    }
                )
                if not calls:
                    result.answer = message.get("content", "")
                    break
                for call in calls:
                    function = call.get("function", {})
                    name = function.get("name", "")
                    arguments = function.get("arguments") or {}
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments or "{}")
                    content, forwarded = self._tool(name, arguments)
                    result.steps.append(Step(name, arguments, forwarded))
                    messages.append({"role": "tool", "content": content, "tool_name": name})
            else:
                result.error = "trop d'appels d'outils"
        except Exception as error:  # noqa: BLE001 — un tour raté n'arrête pas le banc
            result.error = str(error)
        result.wall_s = time.monotonic() - start

    def scenario(self, profile: Profile, scenario: Scenario, run: int) -> list[TurnResult]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.prompt}]
        found = []
        for index, turn in enumerate(scenario.turns):
            result = TurnResult(
                scenario=scenario.key,
                run=run,
                model=profile.name,
                turn=index + 1,
                question=turn.question,
                text=turn.text,
            )
            self.turn(profile, messages, result)
            result.flags = flags_of(result, turn.tools)
            result.verdict = verdict_of(result.flags)
            found.append(result)
        return found

    def warm_up(self, profile: Profile) -> None:
        """Chargement du modèle, hors mesures (la question 1 était posée deux fois)."""
        self._chat(profile, [{"role": "user", "content": "Bonjour"}])


def scenario_verdict(turns: list[TurnResult]) -> str:
    """Pastille d'une question sur plusieurs tours : la pire de ses tours."""
    order = {"ok": 0, "mid": 1, "ko": 2}
    return max((t.verdict for t in turns), key=order.__getitem__)


DOTS = {"ok": "🟢", "mid": "🟠", "ko": "🔴"}


def summary(results: list[TurnResult], models: list[str]) -> str:
    """Résumé en Markdown : par question et par modèle, les pastilles des essais et la durée
    médiane ; puis chaque réponse, pour juger le fond."""
    by: dict[tuple[str, str], list[list[TurnResult]]] = {}
    for r in results:
        runs = by.setdefault((r.scenario, r.model), [])
        while len(runs) < r.run:
            runs.append([])
        runs[r.run - 1].append(r)
    lines = ["| Question | " + " | ".join(models) + " |", "|---" * (len(models) + 1) + "|"]
    for scenario in SCENARIOS:
        cells = []
        for model in models:
            runs = by.get((scenario.key, model), [])
            if not runs:
                cells.append("-")
                continue
            dots = "".join(DOTS[scenario_verdict(turns)] for turns in runs if turns)
            # Durée de la question (premier tour), comme dans le comparatif.
            first = [turns[0].wall_s for turns in runs if turns]
            cells.append(f"{dots} {statistics.median(first):.1f} s")
        lines.append(f"| {scenario.key} | " + " | ".join(cells) + " |")
    lines += ["", "## Réponses", ""]
    for r in results:
        tools = ", ".join(
            f"{s.name}({json.dumps(s.arguments, ensure_ascii=False)})"
            + ("" if s.forwarded else " [non transmis]")
            for s in r.steps
        )
        lines += [
            f"### {r.model} · {r.scenario} · essai {r.run} · tour {r.turn} "
            f"{DOTS[r.verdict]} {r.wall_s:.1f} s",
            f"- Question : {r.text}",
            f"- Outils : {tools or 'aucun'}",
            f"- Réflexion : {r.thinking_chars} caractères ; jetons générés : {r.eval_count}",
            f"- Défauts relevés : {', '.join(r.flags) or 'aucun'}",
            "",
            "> " + (r.answer.strip() or "(vide)").replace("\n", "\n> "),
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wattslot", default=os.environ.get("WATTSLOT_URL"))
    parser.add_argument("--ollama", default=os.environ.get("OLLAMA_URL"))
    parser.add_argument("--profiles", type=Path, default=PROFILES)
    parser.add_argument("--models", help="profils à essayer, séparés par des virgules")
    parser.add_argument("--questions", help="scénarios à jouer (1, 2, 13-15…), par des virgules")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--lang", default="fr")
    parser.add_argument("--prompt-file", type=Path, help="prompt système au lieu du conseillé")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--allow-requests", action="store_true", help="transmettre les demandes confirmées"
    )
    args = parser.parse_args(argv)
    if not args.wattslot or not args.ollama:
        parser.error("--wattslot et --ollama (ou WATTSLOT_URL et OLLAMA_URL) sont requis")

    profiles = load_profiles(args.profiles)
    names = args.models.split(",") if args.models else list(profiles)
    unknown = [n for n in names if n not in profiles]
    if unknown:
        parser.error(f"profils inconnus : {', '.join(unknown)} (connus : {', '.join(profiles)})")
    wanted = set(args.questions.split(",")) if args.questions else None
    scenarios = [s for s in SCENARIOS if wanted is None or s.key in wanted]
    base = args.wattslot.rstrip("/")
    prompt = (
        args.prompt_file.read_text(encoding="utf-8").strip()
        if args.prompt_file
        else get_json(f"{base}/api/assistant/prompt?lang={args.lang}")["prompt"]
    )
    bench = Bench(args.ollama, Mcp(f"{base}/mcp"), prompt, args.allow_requests)

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = args.out / f"{stamp}.jsonl"
    results: list[TurnResult] = []
    with log.open("w", encoding="utf-8") as out:
        for name in names:
            profile = profiles[name]
            print(f"{name} ({profile.model}) : chargement…", file=sys.stderr)
            bench.warm_up(profile)
            for run in range(1, args.runs + 1):
                for scenario in scenarios:
                    for r in bench.scenario(profile, scenario, run):
                        results.append(r)
                        line = {**r.__dict__, "steps": [s.__dict__ for s in r.steps]}
                        out.write(json.dumps(line, ensure_ascii=False) + "\n")
                        out.flush()
                        print(
                            f"  essai {run} · {scenario.key} · tour {r.turn} : "
                            f"{DOTS[r.verdict]} {r.wall_s:.1f} s {', '.join(r.flags)}",
                            file=sys.stderr,
                        )
    report = args.out / f"{stamp}.md"
    report.write_text(summary(results, names) + "\n", encoding="utf-8")
    print(f"Rapport : {report}\nDétail : {log}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
