"""M60 — the company says when it is asleep.

Twice the company stopped thinking for days and nothing said so where a person
would see it: the service was down 15-24 September, and from 7 October every
seat failed with an expired subscription login while the service kept waking
hourly with zero model calls, for eleven days.

The acceptance criteria, each with a test named after it:

* a wake whose agents cannot reach a model raises one critical alert that says
  why in plain words and what to do,
* the alert is raised once and the person is told once, however many wakes it lasts,
* the first wake that reaches a model again closes it and says so,
* a refused or unusable answer is not "asleep": only a provider failure is,
* the facility says, at the top and loudly, whether the company is thinking,
  asleep, or stopped.

Nothing here touches the network or sleeps.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.alerts.tables import Alert
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.errors import ProviderUnavailable
from aurelis.intel.live import CoinbaseCandles
from aurelis.platform.llm.providers import Availability, MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.service.loop import ASLEEP_SOURCE, Service, cycle_once, wake_up_instruction
from aurelis.station.health import company_health

_HOUR = 3600
_START = 1_780_000_000
_EXPIRED = (
    "the Claude Agent SDK could not complete the call: Claude Code returned an error "
    "result: Failed to authenticate: OAuth session expired and could not be refreshed"
)


class _Feed:
    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        now = int(self.clock.now().timestamp())
        count = max(1, (now - _START) // _HOUR)
        rows = [
            [_START + i * _HOUR, 99.0 + i, 101.0 + i, 100.0 + i, 100.0 + i, 5.0]
            for i in range(count)
        ]
        return io.BytesIO(json.dumps(list(reversed(rows))).encode())


class _Catalogue:
    name = "coinbase"
    endpoint = "stand-in://catalogue"

    def products(self) -> list[dict[str, Any]]:
        return []


class _Book:
    name = "coinbase"
    endpoint = "stand-in://book"

    def book(self, symbol: str) -> dict[str, Any]:  # noqa: ARG002
        return {"bids": [["99", "1", 1]], "asks": [["101", "1", 1]]}


class _Trades:
    def trades(self, symbol: str) -> list[dict[str, Any]]:  # noqa: ARG002
        return []


class _Switchable:
    """The stand-in seats, behind a login that can expire and be renewed."""

    name = "mock"

    def __init__(self) -> None:
        self.inner = MockProvider(responder=standins())
        self.expired = False

    def complete(self, request: Any) -> Any:
        if self.expired:
            raise ProviderUnavailable(_EXPIRED)
        return self.inner.complete(request)

    def availability(self) -> Availability:
        return Availability("mock", True, "")


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 200 * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def provider() -> _Switchable:
    return _Switchable()


@pytest.fixture
def company(settings: Settings, clock: FrozenClock, provider: _Switchable) -> Any:
    built = Runtime.build(settings, clock=clock, provider=provider)  # type: ignore[arg-type]
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.grants.grant(
            session,
            source="coinbase",
            desk="crypto",
            instruments=("BTC-USD",),
            granted_by="OPERATOR",
            reason="a test of the asleep alarm, on the record",
            bars=300,
        )
    try:
        yield built
    finally:
        built.close()


def _service(company: Runtime, clock: FrozenClock, told: list[tuple[str, str]]) -> Service:
    return Service(
        company,
        feeds=lambda _grant: CoinbaseCandles(opener=_Feed(clock), pause=0),
        catalogues=lambda _grant: _Catalogue(),
        microstructure=lambda _grant: (_Book(), _Trades()),
        cycles_per_wake=30,
        notifier=lambda title, body: told.append((title, body)),
    )


def _asleep_alerts(company: Runtime) -> list[Alert]:
    with company.database.session() as session:
        return list(
            session.execute(sa.select(Alert).where(Alert.source == ASLEEP_SOURCE)).scalars()
        )


def test_a_wake_that_cannot_reach_a_model_raises_one_alert_that_says_what_to_do(
    company: Runtime, clock: FrozenClock, provider: _Switchable
) -> None:
    provider.expired = True
    told: list[tuple[str, str]] = []
    wake = cycle_once(company, service=_service(company, clock, told))
    assert wake.calls == 0
    assert "ASLEEP" in wake.note
    (alert,) = _asleep_alerts(company)
    assert alert.severity == "critical" and alert.resolved_at is None
    assert alert.ref in wake.incidents
    assert "login" in alert.message and "OAuth session expired" in alert.message
    assert "/login" in alert.recommended_action
    assert told == [("Aurelis is asleep", told[0][1])]
    assert "/login" in told[0][1]


def test_the_alert_and_the_notification_happen_once_however_long_it_sleeps(
    company: Runtime, clock: FrozenClock, provider: _Switchable
) -> None:
    provider.expired = True
    told: list[tuple[str, str]] = []
    first = cycle_once(company, service=_service(company, clock, told))
    for _ in range(3):
        clock.advance(hours=1)
        later = cycle_once(company, service=_service(company, clock, told))
        assert set(first.incidents) & set(later.incidents), "the same open alert"
    assert len(_asleep_alerts(company)) == 1
    assert len(told) == 1


def test_the_first_wake_that_thinks_again_closes_it_and_says_so(
    company: Runtime, clock: FrozenClock, provider: _Switchable
) -> None:
    provider.expired = True
    told: list[tuple[str, str]] = []
    cycle_once(company, service=_service(company, clock, told))
    provider.expired = False
    clock.advance(hours=2)
    wake = cycle_once(company, service=_service(company, clock, told))
    assert wake.calls > 0
    (alert,) = _asleep_alerts(company)
    assert alert.resolved_at is not None
    assert "reached a model again" in (alert.resolution or "")
    assert [title for title, _ in told] == ["Aurelis is asleep", "Aurelis is awake"]


def test_a_company_that_thinks_is_not_asleep(company: Runtime, clock: FrozenClock) -> None:
    told: list[tuple[str, str]] = []
    wake = cycle_once(company, service=_service(company, clock, told))
    assert wake.calls > 0 and "ASLEEP" not in wake.note
    assert _asleep_alerts(company) == []
    assert told == [], "nothing to say when nothing changed"


def test_only_a_provider_failure_marks_a_cycle_as_asleep(
    company: Runtime, provider: _Switchable
) -> None:
    from aurelis.autonomy.loop import run_autonomy

    provider.expired = True
    run = run_autonomy(company, cycles=6, calls=50)
    failed = [c for c in run.cycles if c.outcome == "failed"]
    assert failed and all(c.provider_down for c in failed if "ProviderUnavailable" in c.detail)
    assert run.provider_failures and all("OAuth" in f for f in run.provider_failures)
    assert not any(c.provider_down for c in run.cycles if c.outcome in {"refused", "stopped"})


@pytest.mark.parametrize(
    ("failure", "says", "todo"),
    [
        (_EXPIRED, "login", "/login"),
        ("Not logged in · Please run /login", "login", "/login"),
        ("allowance is exhausted; resets 7:40pm", "allowance", "resets"),
        ("connection reset by peer", "No model could be reached", "internet"),
    ],
)
def test_the_instruction_is_in_words_a_person_can_act_on(
    failure: str, says: str, todo: str
) -> None:
    why, what = wake_up_instruction(failure)
    assert says in why and todo in what


# ------------------------------------------------------------ the station


def test_the_facility_says_loudly_when_the_company_is_asleep(
    company: Runtime, clock: FrozenClock, provider: _Switchable
) -> None:
    from aurelis.station.app import station_app

    provider.expired = True
    cycle_once(company, service=_service(company, clock, []))
    with company.database.session() as session:
        health = company_health(session, clock.now())
    assert health.state == "asleep" and health.alarming
    assert "/login" in health.todo
    for path in ("/", "/now"):
        page = station_app(company).handle(path, {}).body.decode()
        assert "health asleep" in page
        assert "Your company is asleep" in page
        assert "/login" in page


def test_the_facility_says_when_the_company_is_thinking(
    company: Runtime, clock: FrozenClock
) -> None:
    from aurelis.station.app import station_app

    cycle_once(company, service=_service(company, clock, []))
    with company.database.session() as session:
        state = company_health(session, clock.now()).state
    assert state == "thinking"
    page = station_app(company).handle("/now", {}).body.decode()
    assert "class='health" in page


def test_the_facility_says_when_the_service_has_stopped(
    company: Runtime, clock: FrozenClock
) -> None:
    cycle_once(company, service=_service(company, clock, []))
    later = clock.now() + dt.timedelta(hours=5)
    with company.database.session() as session:
        health = company_health(session, later)
    assert health.state == "stopped" and health.alarming
    assert "has not woken" in health.headline
    assert "run-aurelis.ps1" in health.todo
