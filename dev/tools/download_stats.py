"""Nombre de téléchargements de WattSlot : total et par release (lot statistiques de diffusion).

GitHub ne compte les téléchargements que pour les **assets joints aux releases**
(champ ``download_count`` de chaque asset, lisible via l'API publique
``GET /repos/{owner}/{repo}/releases``). WattSlot ne joint aucun fichier à ses releases :
le total est donc 0 tant qu'aucun asset n'est publié — l'app s'installe en clonant le dépôt
(extension Home Assistant) ou en tirant l'image ``ghcr.io/jmcruvellier/wattslot``.

Ce script lit l'API publique et affiche, par release puis au total :

- le nombre de téléchargements de chaque asset (``download_count``) ;
- en option, avec un jeton (``GITHUB_TOKEN``, scope ``repo`` ou ``public_repo``) : les
  **clones** du dépôt via ``GET /repos/{owner}/{repo}/traffic/clones?per=day`` — le
  Supervisor de Home Assistant installant l'extension en clonant le dépôt, c'est le meilleur
  proxy disponible des installations add-on (compteur sur 14 jours seulement, comme l'API).

GHCR ne publie aucun compteur de pulls d'images : pour le canal Docker, aucune API ne
fournit ce chiffre (voir ``docs/installation.md``).

Sans jeton, seule la partie releases fonctionne (API publique). Avec un jeton, ``--clones``
ajoute les clones du dépôt ; si l'API traffic refuse le jeton (le ``GITHUB_TOKEN`` de la CI
peut ne pas suffire, un PAT avec scope ``repo`` ou la permission « Traffic » est plus sûr), le
script avertit et continue sans les clones.

``--history CHEMIN`` ajoute une ligne JSON par exécution (date UTC + snapshot) : c'est ce que
fait le workflow ``.github/workflows/stats.yml`` chaque nuit pour garder l'historique au-delà
de la fenêtre de 14 jours de l'API traffic.

Depuis la racine du dépôt :

    python dev/tools/download_stats.py [--repo jmcruvellier/wattslot] [--json] [--clones]
        [--history dev/stats/history.jsonl]
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API = "https://api.github.com"


def api_get(path: str, token: str | None) -> object:
    """Appel GET de l'API GitHub ; lève une erreur lisible sinon."""
    req = urllib.request.Request(f"{API}{path}", headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def releases_with_assets(owner: str, repo: str, token: str | None) -> list[dict]:
    """Toutes les releases (paginé) avec leurs assets et leur ``download_count``."""
    out = []
    page = 1
    while True:
        batch = api_get(f"/repos/{owner}/{repo}/releases?per_page=100&page={page}", token)
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return out


def clones(owner: str, repo: str, token: str) -> dict:
    """Clones du dépôt par jour (14 derniers jours) — proxy des installations add-on."""
    data = api_get(f"/repos/{owner}/{repo}/traffic/clones?per=day", token)
    return {
        "count": data.get("count", 0),
        "uniques": data.get("uniques", 0),
        "days": [
            {"day": d.get("timestamp"), "count": d.get("count"), "uniques": d.get("uniques")}
            for d in data.get("clones", [])
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default="jmcruvellier/wattslot", help="owner/repo GitHub")
    parser.add_argument("--json", action="store_true", help="sortie JSON brute")
    parser.add_argument(
        "--clones", action="store_true", help="aussi lire les clones (jeton requis)"
    )
    parser.add_argument(
        "--history", metavar="CHEMIN", help="ajoute une ligne JSON (date + snapshot) à ce fichier"
    )
    args = parser.parse_args()

    owner, _, repo = args.repo.partition("/")
    token = os.environ.get("GITHUB_TOKEN")

    releases = releases_with_assets(owner, repo, token)
    per_release = []
    total = 0
    for rel in releases:
        assets = [
            {"name": a["name"], "size": a["size"], "downloads": a["download_count"]}
            for a in rel.get("assets", [])
        ]
        rel_total = sum(a["downloads"] for a in assets)
        total += rel_total
        per_release.append(
            {
                "tag": rel["tag_name"],
                "name": rel.get("name") or rel["tag_name"],
                "published_at": rel.get("published_at"),
                "downloads": rel_total,
                "assets": assets,
            }
        )
    per_release.sort(key=lambda r: r["published_at"] or "", reverse=True)

    result: dict = {"repo": args.repo, "total_downloads": total, "releases": per_release}

    if args.clones:
        if not token:
            print(
                "Avertissement : --clones sans jeton (variable GITHUB_TOKEN), clones ignorés.",
                file=sys.stderr,
            )
        else:
            try:
                result["clones_14j"] = clones(owner, repo, token)
            except (OSError, ValueError) as err:  # jeton refusé par l'API traffic, JSON en erreur
                print(f"Avertissement : clones indisponibles ({err}), ignorés.", file=sys.stderr)

    if args.history:
        path = Path(args.history)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"date": datetime.now(UTC).isoformat(timespec="seconds"), **result}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"Dépôt : {args.repo}")
    print(f"Téléchargements des assets de releases (total) : {total}")
    for rel in per_release:
        date = (rel["published_at"] or "")[:10]
        print(f"  {rel['tag']:<10} {date}  {rel['downloads']:>6} téléchargement(s)")
        for a in rel["assets"]:
            print(f"      {a['name']}  ({a['size']} o)  {a['downloads']} téléchargement(s)")
    if not any(rel["assets"] for rel in per_release):
        print("  (aucun asset joint aux releases : rien à télécharger, total = 0)")
    if "clones_14j" in result:
        c = result["clones_14j"]
        print(f"Clones du dépôt sur 14 jours : {c['count']} (uniques : {c['uniques']})")
        for d in c["days"]:
            day = datetime.fromisoformat(d["day"].replace("Z", "+00:00")).astimezone(UTC)
            print(f"  {day:%Y-%m-%d}  {d['count']:>4} clones  ({d['uniques']} uniques)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
