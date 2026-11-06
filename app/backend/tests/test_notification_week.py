"""Planning de la semaine en notification : jours et heure choisis, une fois par jour choisi,
texte jour par jour d'après la vue Semaine, envoi d'essai ; contre un faux HA."""

import asyncio
import sqlite3
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.test_health import _settings
from tests.test_notifications import FakeHA
from wattslot import notification_events as events
from wattslot import notifications
from wattslot.main import create_app
from wattslot.notifications import NotificationSettings, QuietHours, WeekRule, dispatch, save
from wattslot.storage.database import open_database
from wattslot.views.week import PlannedDevice, WeekDay, WeekView

PARIS = ZoneInfo("Europe/Paris")
PHONE = "notify.mobile_app_phone"
FRIDAY = 4  # le 16/10/2026


def _day(day: date, *devices: tuple[str, int, int]) -> WeekDay:
    return WeekDay(
        day=day,
        production_kwh=10.0,
        grid_import_kwh=1.0,
        grid_import_peak_kwh=0.5,
        grid_export_kwh=2.0,
        devices=[PlannedDevice(device=d, start_min=s, end_min=e) for d, s, e in devices],
    )


def _view(missing: list[date] | None = None) -> WeekView:
    return WeekView(
        days=[
            _day(
                date(2026, 10, 16),
                ("Lave-linge", 9 * 60, 11 * 60),
                ("Sèche-linge", 20 * 60, 21 * 60),
            ),
            _day(
                date(2026, 10, 17),
                ("Lave-vaisselle", 13 * 60 + 30, 15 * 60),
                ("Lave-linge", 11 * 60, 13 * 60),
            ),
            _day(date(2026, 10, 18)),
        ],
        points=[],
        floor_percent=10.0,
        missing_days=missing or [],
    )


def _local(hour: int, minute: int = 59, day: int = 16) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PARIS)


async def _week_of(lang: str) -> WeekView | None:
    return _view()


async def _no_week(lang: str) -> WeekView | None:
    return None


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    return open_database(tmp_path)


def _run(
    client: FakeHA, database: sqlite3.Connection, local: datetime, week_of: Any = _week_of
) -> Any:
    return asyncio.run(
        dispatch(client, database, local.astimezone(UTC), PARIS, None, week_of)  # type: ignore[arg-type]
    )


def _with(**rule: Any) -> NotificationSettings:
    return NotificationSettings(service=PHONE, week=WeekRule(enabled=True, **rule))


def test_text_lists_each_coming_day_and_only_what_is_left_today() -> None:
    message = events.week(_view(), _local(18), "fr")
    assert message == (
        "Vendredi 16 Octobre : Sèche-linge 20h\u201321h\n"
        "Samedi 17 Octobre : Lave-linge 11h\u201313h, Lave-vaisselle 13h30\u201315h\n"
        "Dimanche 18 Octobre : rien à lancer"
    )


def test_text_skips_today_when_nothing_is_left_and_signals_a_short_horizon() -> None:
    view = _view(missing=[date(2026, 10, 19), date(2026, 10, 20)])
    message = events.week(view, _local(21, 30), "en")
    assert message is not None
    assert message.splitlines() == [
        "Saturday, October 17: Lave-linge 11 AM\u20131 PM, Lave-vaisselle 1:30 PM\u20133 PM",
        "Sunday, October 18: nothing to start",
        "No forecast beyond Sunday, October 18, 2026.",
    ]


def test_text_without_any_coming_day() -> None:
    assert events.week(_view(), _local(10, day=19), "fr") is None


def test_week_due_on_chosen_days_from_the_chosen_hour_once() -> None:
    rule = WeekRule(enabled=True, weekdays=[FRIDAY, 6], at=time(18, 0))
    assert not notifications.week_due(rule, None, _local(17))
    assert notifications.week_due(rule, None, _local(18))
    assert not notifications.week_due(rule, ("2026-10-16", "x"), _local(19))
    assert not notifications.week_due(rule, None, _local(18, day=17))  # samedi
    assert notifications.week_due(rule, ("2026-10-16", "x"), _local(18, day=18))


def test_sent_once_on_the_chosen_day(database: sqlite3.Connection) -> None:
    save(database, _with(weekdays=[FRIDAY], at=time(18, 0)))
    client = FakeHA()
    assert _run(client, database, _local(17)) == []
    sent = _run(client, database, _local(18))
    assert [s.kind for s in sent] == ["week"]
    assert client.sent[0]["service_data"]["title"] == "Planning de la semaine"
    assert client.messages()[0].startswith("Vendredi 16 Octobre : Sèche-linge")
    assert _run(client, database, _local(19)) == []
    assert _run(client, database, _local(18, day=17)) == []  # samedi : pas un jour choisi
    assert len(client.sent) == 1


def test_not_sent_by_default_nor_without_a_week(database: sqlite3.Connection) -> None:
    client = FakeHA()
    save(database, NotificationSettings(service=PHONE))
    assert _run(client, database, _local(18)) == []
    save(database, _with(weekdays=[FRIDAY]))
    assert _run(client, database, _local(18), week_of=None) == []
    # Sans plan de la semaine, rien n'est noté : il part au calcul suivant.
    assert _run(client, database, _local(18), week_of=_no_week) == []
    assert notifications.last_sent(database, "week", "plan") is None
    assert len(_run(client, database, _local(19))) == 1


def test_quiet_hours_delay_it_to_the_first_run_after(database: sqlite3.Connection) -> None:
    quiet = QuietHours(start=time(18, 0), end=time(20, 0))
    save(database, _with(weekdays=[FRIDAY], at=time(18, 0), quiet_hours=quiet))
    client = FakeHA()
    assert _run(client, database, _local(18)) == []
    assert len(_run(client, database, _local(20))) == 1


def test_a_failure_is_noted_without_stopping_the_others(database: sqlite3.Connection) -> None:
    async def broken(lang: str) -> WeekView | None:
        raise RuntimeError("vue")

    save(database, _with(weekdays=[FRIDAY]))
    errors: list[str] = []
    asyncio.run(
        dispatch(FakeHA(), database, _local(18).astimezone(UTC), PARIS, errors, broken)  # type: ignore[arg-type]
    )
    assert errors == ["notification week : RuntimeError: vue"]


def test_rule_validation() -> None:
    with pytest.raises(ValidationError):
        WeekRule(weekdays=[])
    with pytest.raises(ValidationError):
        WeekRule(weekdays=[7])
    # Réglages enregistrés avant : le planning de la semaine prend ses valeurs par défaut.
    old = NotificationSettings.model_validate({"service": PHONE})
    assert old.week.enabled is False and old.week.weekdays == [6] and old.week.at == time(18, 0)


def test_test_send(database: sqlite3.Connection) -> None:
    save(database, NotificationSettings(service=PHONE))
    client = FakeHA()
    sent = asyncio.run(
        notifications.send_test(
            client,  # type: ignore[arg-type]
            database,
            "week",
            now=_local(8).astimezone(UTC),
            zone=PARIS,
            week_of=_week_of,
        )
    )
    assert sent.message.startswith(
        "Vendredi 16 Octobre : Lave-linge 9h\u201311h, Sèche-linge 20h\u201321h"
    )
    assert notifications.last_sent(database, "week", "plan") is None
    with pytest.raises(LookupError, match="no_week"):
        asyncio.run(
            notifications.send_test(FakeHA(), database, "week", zone=PARIS, week_of=_no_week)  # type: ignore[arg-type]
        )


def test_settings_route(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/settings/notifications").json()["week"]["weekdays"] == [6]
        body = {"service": PHONE, "week": {"enabled": True, "weekdays": [0, 3], "at": "07:30:00"}}
        saved = api.put("/api/settings/notifications", json=body).json()
        assert saved["week"]["weekdays"] == [0, 3] and saved["week"]["at"] == "07:30:00"
        bad = {**body, "week": {"weekdays": [7]}}
        assert api.put("/api/settings/notifications", json=bad).status_code == 422
        assert api.post("/api/notifications/week/test").status_code == 503
