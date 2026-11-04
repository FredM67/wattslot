"""Outils du serveur MCP (lots 6.1 et 6.2).

Chaque outil rend un objet JSON court, construit sur ce que la v2 calcule déjà (API des vues,
configuration, ingestion, diagnostic), avec les textes déjà rédigés dans la langue réglée pour
les notifications : le LLM n'a rien à recalculer. Tous lisent seulement, sauf
``request_device``, qui dépose une demande comme « Mes demandes » (lot 4.5). Les montants sont
écrits dans la devise de la maison (``currency.amount``).
"""

import hashlib
import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from wattslot import configuration, currency, home_model, notifications, user_requests
from wattslot.aggregation import HOUR
from wattslot.configuration import Behavior
from wattslot.detection import Role
from wattslot.home_assistant import ConnectionState
from wattslot.languages import number
from wattslot.planning.explain import catalog
from wattslot.planning.journal import cycle_appliances
from wattslot.planning.tariff_sources import needs_states, tariff_context
from wattslot.planning.warning_texts import long_date
from wattslot.tariff import NO_CONTEXT, Tariff, TariffContext, TariffKind, off_peak_ranges
from wattslot.views.day import DayView
from wattslot.views.routes import day_view_of, objective_of, week_view_of
from wattslot.views.timeline import Bar

Day = Literal["yesterday", "today", "tomorrow"]

# Qualité de la journée (ensoleillée, mitigée, couverte, lot 5.1), dans la langue réglée.
WEATHER: dict[str, dict[str, str]] = {
    "fr": {
        "sunny": "journée ensoleillée",
        "mixed": "journée mitigée",
        "cloudy": "journée couverte",
    },
    "en": {"sunny": "sunny day", "mixed": "mixed day", "cloudy": "cloudy day"},
    "de": {"sunny": "sonniger Tag", "mixed": "wechselhafter Tag", "cloudy": "bedeckter Tag"},
    "nl": {"sunny": "zonnige dag", "mixed": "wisselvallige dag", "cloudy": "bewolkte dag"},
    "es": {"sunny": "día soleado", "mixed": "día variable", "cloudy": "día nublado"},
    "it": {
        "sunny": "giornata soleggiata",
        "mixed": "giornata variabile",
        "cloudy": "giornata nuvolosa",
    },
}
NO_PLAN = {"error": "no_plan", "hint": "No plan computed yet for this day."}

# Grandeurs « du moment » : puissances et niveau de charge (les compteurs d'énergie, eux,
# passent par get_energy).
NOW_ROLES = {
    Role.STATE_OF_CHARGE: "%",
    Role.POWER_PRODUCED: "W",
    Role.POWER_CONSUMED: "W",
}
# Équipements de la maison par rôle dans le plan : ceux que le calcul place (planned), ceux
# qu'il pourrait placer mais qui sont exclus du calcul (not_planned), le reste.
MANAGED = {Behavior.CYCLE, Behavior.ENERGY_BY_DEADLINE, Behavior.RUNTIME}
HOME_GROUP_OF = {Behavior.PRODUCTION: "solar", Behavior.GRID: "grid"}
HOME_GROUPS = ("planned", "not_planned", "batteries", "solar", "grid", "other_loads")
OBJECTIVE_TEXT = {"autonomy": "import"}  # objectif → texte du catalogue (« objective.… »)
FRESH = timedelta(hours=2)  # au-delà, un relevé ne dit plus « en ce moment »
RUNNING_W = 20  # en dessous, un appareil est en veille


def language(state: Any) -> str:
    """Langue des réponses : celle réglée pour les notifications (lot 5.6)."""
    return notifications.load(state.database).language


def clock(hours: float) -> str:
    """Heure fractionnaire → « 13:05 »."""
    minutes = round(hours * 60)
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def _plain(text: str) -> str:
    """Minuscules sans accents, pour retrouver « lave linge » dans « Lave-linge »."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    letters = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(letters.replace("-", " ").replace("_", " ").split())


def find_name(wanted: str, names: Sequence[str]) -> str | None:
    """Nom d'équipement qui correspond à ``wanted`` (exact, puis contenu, sans accents)."""
    key = _plain(wanted)
    for name in names:
        if _plain(name) == key:
            return name
    for name in names:
        if key and (key in _plain(name) or _plain(name) in key):
            return name
    return None


def _bars(bars: Sequence[Bar]) -> list[dict[str, Any]]:
    return [
        {
            "start": clock(b.start_hour),
            "end": clock(b.end_hour),
            "kwh": round(b.energy_kwh, 2),
            **({"action": b.action} if b.action else {}),
            **({"mode": b.mode} if b.mode else {}),
        }
        for b in bars
    ]


def _max_hour(hour: int) -> str:
    """Heure du maximum de la batterie : le niveau de charge du plan est celui de fin d'heure,
    d'où la tranche « 14:00-15:00 » pour la fin de l'heure 14 (le texte dit « vers 14 h ») ;
    0 : dès le départ, à minuit."""
    return "00:00" if hour <= 0 else f"{hour - 1:02d}:00-{hour:02d}:00"


def _summary(view: DayView, lang: str) -> dict[str, Any]:
    s = view.summary
    found: dict[str, Any] = {
        "production_kwh": round(s.production_kwh, 2),
        "grid_import_kwh": round(s.grid_import_kwh, 2),
        "grid_export_kwh": round(s.grid_export_kwh, 2),
    }
    if view.battery_capacity_kwh is not None:
        found.update(
            battery_end_percent=round(s.soc_end_percent),
            battery_max_percent=round(s.soc_max_percent),
            battery_max_at=_max_hour(s.soc_max_hour),
        )
    # Indicateurs de la journée entière (Aujourd'hui, Hier : heures passées mesurées).
    found.update(_indicators(view, lang))
    return found


def _indicators(view: DayView, lang: str) -> dict[str, Any]:
    """Coût de la journée (achat moins revente, abonnement compris), part de la production
    consommée sur place, CO₂ quand il est connu."""
    i = view.indicators
    if i is None:
        return {}
    found: dict[str, Any] = {"cost": currency.amount(i.cost_eur, lang)}
    if i.self_consumption_percent is not None:
        found["self_consumption_percent"] = round(i.self_consumption_percent)
    if i.co2_kg is not None:
        found["co2_kg"] = round(i.co2_kg, 1)
    return found


def _next_action(view: DayView, lang: str) -> dict[str, Any] | None:
    """Prochain appareil à lancer aujourd'hui, et les autres départs permis avec leur écart de
    coût par rapport au plan."""
    action = view.next_action
    if action is None:
        return None
    found: dict[str, Any] = {
        "device": action.device,
        "start": clock(action.start_min / 60),
        "end": clock(action.end_min / 60),
    }
    if action.explanation:
        found["why"] = action.explanation
    if action.alternatives:
        found["other_starts"] = [
            {
                "start": clock(a.start_min / 60),
                "extra_cost": currency.amount(a.cost_eur_delta, lang, signed=True),
            }
            for a in action.alternatives
        ]
    return found


# Lignes du texte de recommandation reprises par le résumé : le bilan du plan au moment du calcul
# (« Bilan prévu : 0,99 € ») et la batterie en kWh, avec l'heure du maximum du plan. À côté du
# coût de la journée entière et de la batterie en pourcentage du résumé, deux chiffres pour une
# même question : les modèles prenaient l'un pour l'autre.
FIGURE_LINES = ("battery", "balance")


def _pattern(template: str) -> re.Pattern[str]:
    """Début d'une ligne écrite d'après ``template`` (« {x} » : n'importe quel texte)."""
    parts = re.split(r"\{[a-z_]+\}", template)
    return re.compile(".+?".join(re.escape(p) for p in parts))


def plan_text(text: str | None, lang: str) -> str | None:
    """Texte de recommandation sans les lignes de chiffres que le résumé donne déjà."""
    if text is None:
        return None
    texts = catalog(lang)
    patterns = [_pattern(texts[f"recommendation.{key}"]) for key in FIGURE_LINES]
    lines = [line for line in text.split("\n") if not any(p.match(line) for p in patterns)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


async def _next_planned(state: Any, after: date) -> dict[str, Any] | None:
    """Premier appareil que l'horizon place après ``after``."""
    week = await week_view_of(state, language(state))
    for other in week.days if week else []:
        if other.day > after and other.devices:
            first = min(other.devices, key=lambda p: p.start_min)
            return {
                "day": other.day.isoformat(),
                "device": first.device,
                "start": clock(first.start_min / 60),
                "end": clock(first.end_min / 60),
            }
    return None


async def get_day_plan(state: Any, day: Day = "today") -> dict[str, Any]:
    lang = language(state)
    view = await day_view_of(state, day, lang)
    if view is None:
        return NO_PLAN
    found: dict[str, Any] = {
        "day": view.day.isoformat(),
        "computed_at": view.computed_at.isoformat(timespec="minutes") if view.computed_at else None,
        "recommendation": plan_text(view.recommendation, lang),
        "summary": _summary(view, lang),
        "warnings": [n.text for n in view.notices],
    }
    if day == "today":
        # Une phrase plutôt qu'une valeur vide : les modèles recopiaient le champ « null ».
        found["next_appliance"] = _next_action(view, lang) or catalog(lang)["assistant.no_next"]
        if view.next_action is None:
            later = await _next_planned(state, view.day)
            if later is not None:
                found["next_planned"] = later
    if day != "today":
        # Texte rédigé comme la notification du jour : « aujourd'hui » y désigne ce jour-là.
        found["note"] = f'In the recommendation text, "today" means {view.day.isoformat()}.'
    return found


def _status_text(status: str, shift_min: int | None, lang: str) -> str:
    """État du cycle en une phrase (« on_time » était recopié tel quel)."""
    texts = catalog(lang)
    if status == "shifted" and shift_min:
        key = "late" if shift_min > 0 else "early"
        return texts[f"assistant.status.{key}"].format(minutes=abs(shift_min))
    return texts[f"assistant.status.{'on_time' if status == 'shifted' else status}"]


async def explain_device(state: Any, device: str, day: Day = "today") -> dict[str, Any]:
    view = await day_view_of(state, day, language(state))
    if view is None:
        return NO_PLAN
    names = [r.device for r in view.timeline.rows] + [e.device for e in view.explanations]
    name = find_name(device, list(dict.fromkeys(names)))
    if name is None:
        return await _not_planned(state, device, view.day, list(dict.fromkeys(names)))
    row = next((r for r in view.timeline.rows if r.device == name), None)
    status = next((s for s in view.timeline.statuses if s.device == name), None)
    explanation = next((e.text for e in view.explanations if e.device == name), None)
    found: dict[str, Any] = {"device": name, "day": view.day.isoformat()}
    if row is not None:
        found["planned"] = _bars(row.planned)
        if row.actual:
            found["actual"] = _bars(row.actual)
    if status is not None:
        found["status"] = _status_text(status.status, status.shift_min, language(state))
    if explanation:
        found["why"] = explanation
    return found


async def _not_planned(state: Any, device: str, day: date, planned: list[str]) -> dict[str, Any]:
    """Équipement absent du plan de ce jour : s'il est dans la maison, il n'est simplement pas
    prévu (rien de demandé ni d'échu) ; on dit quand l'horizon le place et s'il peut être
    demandé. Sinon, équipement inconnu."""
    home = home_model.load(state.graph)
    name = find_name(device, [d.name for d in home.devices])
    if name is None:
        return {"error": "unknown_device", "planned_devices": planned}
    # Textes dans la langue réglée et sans nom d'outil : les modèles les recopient tels quels.
    texts = catalog(language(state))
    found: dict[str, Any] = {
        "device": name,
        "day": day.isoformat(),
        "scheduled": False,
        "reason": texts["assistant.not_planned"],
    }
    week = await week_view_of(state, language(state))
    for other in week.days if week else []:
        if other.day <= day:
            continue
        slot = next((p for p in other.devices if find_name(p.device, [name]) is not None), None)
        if slot is not None:
            found["next_planned"] = {
                "day": other.day.isoformat(),
                "start": clock(slot.start_min / 60),
                "end": clock(slot.end_min / 60),
            }
            break
    requestable = cycle_appliances(home, configuration.load(state.graph))
    if any(a.name == name for a in requestable):
        found["hint"] = texts["assistant.can_request"]
    return found


def _when(day: date, today: date, lang: str) -> str:
    """« aujourd'hui », « demain », sinon la date en toutes lettres."""
    texts = catalog(lang)
    if day == today:
        return texts["assistant.today"]
    if day == today + timedelta(days=1):
        return texts["assistant.tomorrow"]
    return long_date(day, lang)


async def get_week(state: Any) -> dict[str, Any]:
    lang = language(state)
    view = await week_view_of(state, lang)
    if view is None:
        return NO_PLAN
    today = datetime.now(state.raw.zone).date()
    return {
        # Le premier jour est aujourd'hui : sans le dire, « le reste de la semaine » le comptait.
        "today": today.isoformat(),
        "days": [
            {
                "day": d.day.isoformat(),
                # En mots aussi : avec la seule date, un modèle comptait encore aujourd'hui.
                "when": _when(d.day, today, lang),
                "production_kwh": round(d.production_kwh, 1),
                # La qualité en toutes lettres seulement : « sunny » était recopié tel quel.
                **({"weather": WEATHER[lang][d.weather]} if d.weather else {}),
                **(
                    {"battery_end_percent": round(d.soc_end_percent)}
                    if d.soc_end_percent is not None
                    else {}
                ),
                "grid_import_kwh": round(d.grid_import_kwh, 2),
                "devices": [
                    {
                        "device": p.device,
                        "start": clock(p.start_min / 60),
                        "end": clock(p.end_min / 60),
                    }
                    for p in d.devices
                ],
                "warnings": [n.text for n in d.notices],
            }
            for d in view.days
        ],
        "warnings": [n.text for n in view.notices],
    }


async def get_current_status(state: Any) -> dict[str, Any]:
    ingestor = state.ingestor
    if ingestor is None:
        return {"error": "not_connected", "hint": "Home Assistant is not connected."}
    names = {
        sensor.entity_id: device.name
        for device in home_model.load(state.graph).devices
        for sensor in device.sensors
    }
    now = datetime.now(UTC)
    # HA n'envoie un relevé qu'au changement : un niveau de charge stable reste valable, une
    # puissance figée depuis longtemps vient d'un capteur muet (panneaux la nuit…).
    fresh = [
        e
        for e in ingestor.status().entities
        if e.role in NOW_ROLES
        and e.last_value is not None
        and e.last_time is not None
        and (e.role is Role.STATE_OF_CHARGE or now - e.last_time <= FRESH)
    ]
    found: dict[str, Any] = {}
    # Phrase « En ce moment » de Planning (lot 6b.3) : qui alimente la maison, au dernier quart
    # d'heure clos.
    view = await day_view_of(state, "today", language(state))
    if view is not None and view.now is not None and view.now.sentence:
        found["now"] = view.now.sentence
        found["off_peak"] = view.now.off_peak
    # Un résumé plutôt que tous les relevés (~2 000 tokens, heures en UTC) : le niveau de la
    # batterie s'y cherchait sous le nom de l'appareil.
    charge = [e.last_value for e in fresh if e.role is Role.STATE_OF_CHARGE]
    if charge:
        found["battery_percent"] = round(sum(charge) / len(charge))
    solar = [e.last_value for e in fresh if e.role is Role.POWER_PRODUCED]
    if solar:
        found["solar_power_w"] = round(sum(solar))
    running = sorted(
        (
            (names.get(e.entity_id, e.entity_id), round(e.last_value))
            for e in fresh
            if e.role is Role.POWER_CONSUMED and e.last_value >= RUNNING_W
        ),
        key=lambda r: -r[1],
    )
    found["appliances_on"] = [{"device": d, "power_w": w} for d, w in running]
    if fresh:
        latest = max(e.last_time for e in fresh if e.last_time is not None)
        found["measured_at"] = latest.astimezone(state.raw.zone).strftime("%H:%M")
    return found


# Totaux mesurés tirés des compteurs d'énergie de la maison, par rôle.
TOTALS = {
    Role.ENERGY_PRODUCED: "production_kwh",
    Role.ENERGY_IMPORTED: "grid_import_kwh",
    Role.ENERGY_EXPORTED: "grid_export_kwh",
    Role.ENERGY_CHARGED: "battery_charge_kwh",
    Role.ENERGY_DISCHARGED: "battery_discharge_kwh",
}


def day_of(state: Any, day: str) -> date | None:
    """« today », « yesterday » ou une date AAAA-MM-JJ, dans le fuseau de la maison."""
    today = datetime.now(state.raw.zone).date()
    if day == "today":
        return today
    if day == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(day)
    except ValueError:
        return None


def measured_energy(state: Any, day: date) -> dict[str, Any] | None:
    """Énergie mesurée d'un jour, tirée des agrégats horaires des compteurs (lot 1.3) : totaux
    par rôle, consommation de la maison par bilan, et par équipement mesuré. ``None`` sans
    agrégats (HA non connecté)."""
    aggregator = state.aggregator
    if aggregator is None:
        return None
    zone = state.raw.zone
    start = datetime.combine(day, time(), zone)
    end = datetime.combine(day + timedelta(days=1), time(), zone)
    totals: dict[str, float] = {}
    devices: dict[str, float] = {}
    for device in home_model.load(state.graph).devices:
        for sensor in device.sensors:
            if sensor.role not in TOTALS and sensor.role is not Role.ENERGY_CONSUMED:
                continue
            values = [
                a.energy_kwh
                for a in aggregator.read(sensor.entity_id, HOUR, start, end)
                if a.energy_kwh is not None
            ]
            if not values:
                continue
            kwh = sum(values)
            if sensor.role is Role.ENERGY_CONSUMED:
                devices[device.name] = devices.get(device.name, 0.0) + kwh
            else:
                key = TOTALS[sensor.role]
                totals[key] = totals.get(key, 0.0) + kwh
    if not totals and not devices:
        return {}
    found: dict[str, Any] = {key: round(value, 2) for key, value in totals.items()}
    if "production_kwh" in totals and "grid_import_kwh" in totals:
        # Bilan de la maison : produit + acheté - injecté + rendu par la batterie - stocké.
        found["consumption_kwh"] = round(
            totals["production_kwh"]
            + totals["grid_import_kwh"]
            - totals.get("grid_export_kwh", 0.0)
            + totals.get("battery_discharge_kwh", 0.0)
            - totals.get("battery_charge_kwh", 0.0),
            2,
        )
    if devices:
        found["devices"] = {name: round(kwh, 2) for name, kwh in devices.items()}
    return found


async def get_energy(state: Any, day: str = "today") -> dict[str, Any]:
    """Énergie mesurée d'un jour (agrégats, n'importe quel jour gardé), et ce que prévoyait le
    plan quand il existe encore (aujourd'hui, hier)."""
    wanted = day_of(state, day)
    if wanted is None:
        return {"error": "invalid_date", "hint": "Use today, yesterday or YYYY-MM-DD."}
    if wanted > datetime.now(state.raw.zone).date():
        return {"error": "invalid_date", "hint": "The day is in the future: see get_forecast."}
    measured = measured_energy(state, wanted)
    view = None
    for kind in ("today", "yesterday"):
        found = await day_view_of(state, kind, language(state))
        if found is not None and found.day == wanted:
            view = found
            break
    if not measured and view is None:
        return {
            "error": "no_data",
            "hint": "No measurement kept for this day, and no plan.",
        }
    result: dict[str, Any] = {"day": wanted.isoformat(), "measured": measured or None}
    if view is not None:
        result["planned"] = {
            "production_kwh": round(sum(h.production_kwh for h in view.hours), 2),
            "consumption_kwh": round(sum(h.consumption_kwh for h in view.hours), 2),
            "devices": {
                row.device: round(sum(b.energy_kwh for b in row.planned), 2)
                for row in view.timeline.rows
                if row.kind != "battery"
            },
        }
    return result


async def get_forecast(state: Any, day: Literal["today", "tomorrow"] = "today") -> dict[str, Any]:
    view = await day_view_of(state, day, language(state))
    if view is None:
        return NO_PLAN
    if not view.solar:  # maison sans installation solaire (lot 7.4)
        return {"day": view.day.isoformat(), "solar_installation": False, "production_kwh": 0}
    return {
        "day": view.day.isoformat(),
        "production_kwh": round(view.weather.production_kwh, 1),
        **(
            {"weather": WEATHER[language(state)][view.weather.quality]}
            if view.weather.quality
            else {}
        ),
        "hourly_kwh": {
            f"{h.hour:02d}:00": round(h.production_kwh, 2) for h in view.hours if h.production_kwh
        },
    }


def get_home(state: Any) -> dict[str, Any]:
    home = home_model.load(state.graph)
    saved = configuration.load(state.graph)
    settings = {d.key: d for d in configuration.effective(home, saved).devices}
    battery = configuration.battery_of(saved)
    tariff = configuration.tariff_of(saved)
    lang = language(state)
    texts = catalog(lang)
    preset = objective_of(state, saved).value
    # Groupes par rôle dans le plan plutôt que les codes de la configuration : « scheduled »
    # valait vrai pour tout (même le réseau), d'où « tous les équipements sont planifiés ».
    groups: dict[str, list[Any]] = {key: [] for key in HOME_GROUPS}
    for d in home.devices:
        setting = settings.get(d.key)
        behavior = setting.behavior if setting else Behavior.UNCONTROLLED
        if behavior is Behavior.STORAGE:
            # Valeurs écrites dans la langue réglée (« 5,12 kWh ») et réserve nommée pour ce
            # qu'elle est : « floor_percent: 12.0 » se lisait « 12.0 % d'espace ».
            groups["batteries"].append(
                {
                    "name": d.name,
                    **(
                        {"capacity": f"{number(d.capacity_kwh, lang, 2)}\u00a0kWh"}
                        if d.capacity_kwh
                        else {}
                    ),
                    "never_below": f"{number(battery.floor_percent, lang, 0)}\u00a0%",
                }
            )
        elif behavior in MANAGED:
            groups["planned" if setting and setting.planned else "not_planned"].append(d.name)
        else:
            groups[HOME_GROUP_OF.get(behavior, "other_loads")].append(d.name)
    return {
        **{key: values for key, values in groups.items() if values},
        "tariff": texts[f"assistant.tariff.{tariff.kind.value}"],
        "objective": texts[f"objective.{OBJECTIVE_TEXT.get(preset, preset)}"],
    }


async def get_problems(problems: Callable[[], Awaitable[Sequence[Any]]]) -> dict[str, Any]:
    found = await problems()
    return {
        "problems": [
            {
                "severity": p.severity.value,
                "code": p.code,
                **({"details": p.params} if p.params else {}),
            }
            for p in found
        ]
    }


def confirm_code(key: str, latest: date | None, today: date) -> str:
    """Code à rendre pour confirmer une demande : propre à l'équipement, à la date limite et au
    jour, il ne se devine pas ; un modèle doit donc d'abord rendre la question à l'utilisateur."""
    seed = f"{key}|{latest.isoformat() if latest else ''}|{today.isoformat()}"
    return hashlib.sha256(seed.encode()).hexdigest()[:6]


def request_device(
    state: Any, device: str, latest_date: str | None = None, code: str | None = None
) -> dict[str, Any]:
    """Demande pour un équipement (lot 4.5), au plus tard ``latest_date`` (AAAA-MM-JJ) ; une
    demande déjà ouverte pour lui change seulement de date. Le calcul suivant la place.

    En deux temps : sans code, rien n'est déposé, l'outil rend la question à poser et le code ;
    la demande n'est déposée qu'avec ce code, donc après l'accord de l'utilisateur. Les deux
    modèles essayés déposaient la demande sans rien demander malgré la règle du prompt."""
    home = home_model.load(state.graph)
    requestable = cycle_appliances(home, configuration.load(state.graph))
    names = [a.name for a in requestable]
    name = find_name(device, names)
    if name is None:
        return {"error": "unknown_device", "devices": names}
    today = datetime.now(state.raw.zone).date()
    # « Avant demain soir » : les modèles passent « tomorrow » sans connaître la date du jour.
    relative = {"today": today, "tomorrow": today + timedelta(days=1)}
    latest = None
    if latest_date:
        try:
            latest = relative.get(latest_date.strip().lower()) or date.fromisoformat(latest_date)
        except ValueError:
            return {
                "error": "invalid_date",
                "hint": f"Use today, tomorrow or YYYY-MM-DD; today is {today.isoformat()}.",
            }
        if latest < today:
            return {
                "error": "invalid_date",
                "hint": f"The date is in the past; today is {today.isoformat()}.",
            }
    key = next(a.key for a in requestable if a.name == name)
    expected = confirm_code(key, latest, today)
    if code is None:
        lang = language(state)
        texts = catalog(lang)
        question = (
            texts["assistant.request_by"].format(device=name, date=long_date(latest, lang))
            if latest
            else texts["assistant.request"].format(device=name)
        )
        return {
            "device": name,
            "latest_date": latest.isoformat() if latest else None,
            "filed": False,
            "question": question,
            "confirm_code": expected,
            "next": "Nothing filed yet. Ask the user this question as it is, without the code. "
            "Only if they agree, call again with the same device and latest_date and this "
            "confirm_code.",
        }
    if code.strip() != expected:
        return {
            "error": "invalid_confirm_code",
            "hint": "Call request_device without confirm_code to get the question and the code.",
        }
    found = user_requests.ask(state.database, key, latest, datetime.now(UTC))
    return {
        "device": name,
        "latest_date": found.latest.isoformat() if found.latest else None,
        "filed": True,
        "status": found.status.value,
        "note": "Filed. The next computation of the plan places it at the best time. Do not "
        "show the code to the user.",
    }


def get_requests(state: Any) -> dict[str, Any]:
    """Demandes ouvertes, puis celles closes depuis une semaine, comme « Mes demandes »."""
    names = {d.key: d.name for d in home_model.load(state.graph).devices}
    return {
        "requests": [
            {
                "device": names.get(r.device, r.device),
                "status": r.status.value,
                "asked_on": r.created_at.astimezone(state.raw.zone).date().isoformat(),
                "latest_date": r.latest.isoformat() if r.latest else None,
                **({"launched_on": r.launched_on.isoformat()} if r.launched_on else {}),
            }
            for r in user_requests.recent(state.database, datetime.now(UTC))
        ]
    }


async def _tariff_context(state: Any, tariff: Tariff, today: date) -> TariffContext:
    """Couleur des jours et prix publiés, lus dans HA comme pour le calcul ; sans HA, aucun."""
    client = getattr(state, "home_assistant", None)
    if not needs_states(tariff) or client is None:
        return NO_CONTEXT
    if client.status.state is not ConnectionState.CONNECTED:
        return NO_CONTEXT
    try:
        states = await client.command("get_states")
    except Exception:  # noqa: BLE001 — HA injoignable à cet instant : prix saisis seulement
        return NO_CONTEXT
    return tariff_context(tariff, states or [], today, state.raw.zone)


def _price_ranges(prices: dict[int, float], lang: str) -> list[dict[str, str]]:
    """Heures consécutives au même prix, réunies : 00:00-06:00, « 0,210 €/kWh »."""
    ranges: list[tuple[int, int, float]] = []
    for hour in range(24):
        if ranges and ranges[-1][2] == prices[hour]:
            ranges[-1] = (ranges[-1][0], hour + 1, prices[hour])
        else:
            ranges.append((hour, hour + 1, prices[hour]))
    return [
        {"start": clock(start), "end": clock(end), "price": currency.per_kwh(price, lang)}
        for start, end, price in ranges
    ]


async def get_tariff(state: Any, day: Literal["today", "tomorrow"] = "today") -> dict[str, Any]:
    """Prix du kWh par plage horaire, heures creuses, couleur du jour (Tempo) ; prix de revente
    quand il y en a un."""
    lang = language(state)
    tariff = configuration.tariff_of(configuration.load(state.graph))
    today = datetime.now(state.raw.zone).date()
    wanted = today + timedelta(days=1) if day == "tomorrow" else today
    context = await _tariff_context(state, tariff, today)
    found: dict[str, Any] = {
        "day": wanted.isoformat(),
        "tariff": catalog(lang)[f"assistant.tariff.{tariff.kind.value}"],
        "prices": _price_ranges(tariff.hourly(wanted, context), lang),
        "off_peak": [
            {"start": clock(start), "end": clock(end)}
            for start, end in off_peak_ranges(tariff, wanted, context)
        ],
    }
    if tariff.kind is TariffKind.DAY_COLOR:
        found["color"] = context.colors.get(wanted)  # aucune : pas encore annoncée
        if found["color"] is None:
            found["note"] = "Color of this day not announced yet: default prices shown."
    if tariff.kind is TariffKind.DYNAMIC and wanted not in context.prices:
        found["note"] = "Prices of this day not published yet: default price shown."
    export = tariff.export_hourly(wanted, context)
    if any(export.values()):
        found["export_prices"] = _price_ranges(export, lang)
    return found
