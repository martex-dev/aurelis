"""M27 — the company runs for days, and records what broke.

The acceptance criteria, each with a test named after it:

* the service fetches nothing without a grant, and a grant is a person's
  decision on the record that cannot be widened, only revoked,
* one wake fetches under the grants, settles what a recording covers, seats
  the judges, and writes a row whatever happened,
* a vendor outage is an incident and the wake continues,
* a provider outage is an incident and the wake continues,
* the daily model-call budget binds before the limit, not after,
* the service runs for its duration, then stops and says why,
* the forward record accumulates across wakes,
* the service is legible on the station.

**Nothing here touches the network or sleeps.** The clock is frozen and the
sleeper advances it; the feed is a recorded payload that grows with the clock.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aurelis.alerts.tables import Alert
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.errors import IntegrityViolation, ProviderUnavailable
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.tables import Thesis
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.service.grants import Grants
from aurelis.service.loop import Service, cycle_once, serve
from aurelis.service.tables import DataGrant, ServiceCycle

_HOUR = 3600
_START = 1_780_000_000


class _GrowingFeed:
    """A vendor whose history grows with the clock: every call returns the
    bars that opened before now, so a later wake sees more than an earlier one."""

    def __init__(self, clock: FrozenClock, *, base: int = 100, step: int = 1) -> None:
        self.clock = clock
        self.base = base
        self.step = step
        self.down = False
        self.calls = 0

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        self.calls += 1
        if self.down:
            raise OSError("connection refused")
        now = int(self.clock.now().timestamp())
        count = max(1, (now - _START) // _HOUR)
        rows = [
            [
                _START + i * _HOUR,
                float(self.base + i * self.step) - 1,
                float(self.base + i * self.step) + 1,
                float(self.base + i * self.step),
                float(self.base + i * self.step),
                5.0,
            ]
            for i in range(count)
        ]
        return io.BytesIO(json.dumps(list(reversed(rows))).encode())


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 200 * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _service(company: Runtime, clock: FrozenClock, feed: _GrowingFeed, **kwargs: Any) -> Service:
    return Service(
        company,
        feeds=lambda _grant: CoinbaseCandles(opener=feed, pause=0),
        cycles_per_wake=kwargs.pop("cycles_per_wake", 30),
        **kwargs,
    )


def _grant(company: Runtime, *instruments: str) -> DataGrant:
    with company.database.session() as session:
        return company.grants.grant(
            session,
            source="coinbase",
            desk="crypto",
            instruments=instruments or ("BTC-USD",),
            granted_by="OPERATOR",
            reason="a test of the service, on the record",
            bars=300,
        )


def _theses(company: Runtime) -> list[Thesis]:
    with company.database.session() as session:
        return list(session.execute(sa.select(Thesis).order_by(Thesis.ref)).scalars())


# ------------------------------------------------------------ the grant


def test_the_service_fetches_nothing_without_a_grant(company: Runtime, clock: FrozenClock) -> None:
    feed = _GrowingFeed(clock)
    wake = cycle_once(company, service=_service(company, clock, feed))
    assert feed.calls == 0
    assert wake.fetched == ()
    assert "no active data grant" in wake.note
    with company.database.session() as session:
        assert (
            session.execute(sa.select(sa.func.count()).select_from(ServiceCycle)).scalar_one() == 1
        )


def test_a_grant_is_a_persons_decision_on_the_record_and_cannot_be_widened(
    company: Runtime,
) -> None:
    grant = _grant(company, "BTC-USD")
    assert grant.granted_by == "OPERATOR" and grant.reason
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="cannot be changed"),
    ):
        session.execute(
            sa.text("UPDATE data_grants SET instruments = :i WHERE ref = :ref"),
            {"i": json.dumps(["BTC-USD", "DOGE-USD"]), "ref": grant.ref},
        )
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="never deleted"),
    ):
        session.execute(sa.text("DELETE FROM data_grants WHERE ref = :ref"), {"ref": grant.ref})
    with company.database.session() as session:
        company.grants.revoke(session, grant.ref, by="OPERATOR")
        assert Grants.active(session) == []
    with (
        company.database.session() as session,
        pytest.raises(IntegrityViolation, match="already revoked"),
    ):
        company.grants.revoke(session, grant.ref, by="OPERATOR")
    with company.database.session() as session:
        kinds = [
            k
            for (k,) in session.execute(
                sa.text("SELECT kind FROM events WHERE kind LIKE 'service.%'")
            )
        ]
    assert "service.data_granted" in kinds and "service.data_grant_revoked" in kinds


def test_an_unknown_vendor_cannot_be_granted(company: Runtime) -> None:
    with (
        company.database.session() as session,
        pytest.raises(IntegrityViolation, match="not a vendor"),
    ):
        company.grants.grant(
            session,
            source="scraper",
            desk="crypto",
            instruments=("BTC-USD",),
            granted_by="OPERATOR",
            reason="this should be refused",
        )


def test_a_revoked_grant_is_not_fetched(company: Runtime, clock: FrozenClock) -> None:
    grant = _grant(company, "BTC-USD")
    with company.database.session() as session:
        company.grants.revoke(session, grant.ref, by="OPERATOR")
    feed = _GrowingFeed(clock)
    wake = cycle_once(company, service=_service(company, clock, feed))
    assert feed.calls == 0 and wake.fetched == ()


# ------------------------------------------------------------ one wake


def test_one_wake_fetches_settles_seats_and_writes_a_row(
    company: Runtime, clock: FrozenClock
) -> None:
    _grant(company, "BTC-USD", "ETH-USD")
    feed = _GrowingFeed(clock)
    first = cycle_once(company, service=_service(company, clock, feed))
    assert len(first.fetched) == 2 and first.fetch_failures == 0
    assert first.run_ref is not None and first.run_ref.startswith("RUN-A-")
    assert first.calls > 0
    sealed = _theses(company)
    assert sealed, "the loop seated judges on the fresh recordings"
    assert all(t.scored_at is None for t in sealed)

    clock.advance(hours=25)
    second = cycle_once(company, service=_service(company, clock, feed))
    assert len(second.fetched) == 2
    assert second.scored == len(sealed), "every 24h view was settled by the fresh recording"
    assert second.pending == 0
    after = _theses(company)
    assert len(after) > len(sealed), "and the judges were seated again"

    with company.database.session() as session:
        rows = list(session.execute(sa.select(ServiceCycle).order_by(ServiceCycle.ref)).scalars())
        events = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'service.woke'")
        ).scalar_one()
    assert [r.scored for r in rows] == [0, len(sealed)]
    assert events == 2


def test_the_forward_record_accumulates_across_wakes(company: Runtime, clock: FrozenClock) -> None:
    from aurelis.judgement.calibration import company_calibration

    _grant(company, "BTC-USD")
    feed = _GrowingFeed(clock)
    service = _service(company, clock, feed)
    outcome = serve(
        company,
        interval_seconds=25 * _HOUR,
        max_wakes=4,
        service=service,
        sleeper=lambda seconds: clock.advance(seconds=seconds),
    )
    assert len(outcome.wakes) == 4
    with company.database.session() as session:
        record = company_calibration(session)["overall"][0]
    assert record.scored >= 3 * (len(_theses(company)) // 4), "most views have been scored"
    assert record.scored > 0 and record.mean_brier is not None


# ------------------------------------------------------------ failure recovery


def test_a_vendor_outage_is_an_incident_and_the_wake_continues(
    company: Runtime, clock: FrozenClock
) -> None:
    _grant(company, "BTC-USD")
    feed = _GrowingFeed(clock)
    feed.down = True
    wake = cycle_once(company, service=_service(company, clock, feed))
    assert wake.fetched == () and wake.fetch_failures == 1
    assert len(wake.incidents) == 1
    with company.database.session() as session:
        alert = session.execute(sa.select(Alert).where(Alert.ref == wake.incidents[0])).scalar_one()
    assert alert.source == "service.fetch" and alert.severity == "warning"
    assert "Nothing was stored" in alert.recommended_action
    assert wake.run_ref is not None, "the loop still ran"

    feed.down = False
    again = cycle_once(company, service=_service(company, clock, feed))
    assert len(again.fetched) == 1 and again.incidents == ()


def test_a_provider_outage_is_an_incident_and_the_wake_continues(
    settings: Settings, clock: FrozenClock
) -> None:
    class _Down:
        name = "mock"

        def complete(self, request: object) -> object:
            raise ProviderUnavailable("allowance is exhausted; resets 7:40pm")

        def availability(self) -> object:
            from aurelis.platform.llm.providers import Availability

            return Availability("mock", True, "")

    built = Runtime.build(settings, clock=clock, provider=_Down())  # type: ignore[arg-type]
    built.initialise()
    built.staff()
    try:
        _grant(built, "BTC-USD")
        feed = _GrowingFeed(clock)
        wake = cycle_once(built, service=_service(built, clock, feed))
        assert len(wake.fetched) == 1, "fetching does not need a model"
        assert wake.run_ref is not None, "the loop ran and recorded the failed action"
        assert _theses(built) == []
        with built.database.session() as session:
            cycles = session.execute(sa.text("SELECT outcome FROM autonomy_cycles")).all()
        assert ("failed",) in cycles
    finally:
        built.close()


def test_the_daily_call_budget_binds_before_the_limit(company: Runtime, clock: FrozenClock) -> None:
    _grant(company, "BTC-USD", "ETH-USD")
    feed = _GrowingFeed(clock)
    tight = _service(company, clock, feed, calls_per_day=4)
    wake = cycle_once(company, service=tight)
    assert wake.calls <= 4
    assert wake.calls_left_today == 4 - wake.calls
    spent = cycle_once(company, service=tight, at=clock.now())
    assert spent.run_ref is None
    assert "budget" in spent.note
    clock.advance(hours=25)
    tomorrow = cycle_once(company, service=tight)
    assert tomorrow.run_ref is not None, "a rolling day later the budget is back"


# ------------------------------------------------------------ the loop between wakes


def test_the_service_runs_for_its_duration_then_stops_and_says_why(
    company: Runtime, clock: FrozenClock
) -> None:
    _grant(company, "BTC-USD")
    feed = _GrowingFeed(clock)
    slept: list[float] = []

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds=seconds)

    outcome = serve(
        company,
        interval_seconds=_HOUR,
        duration_seconds=3 * _HOUR + 10,
        service=_service(company, clock, feed),
        sleeper=sleeper,
    )
    assert len(outcome.wakes) == 4, "wakes at 0h, 1h, 2h, 3h; the 4h wake would pass the duration"
    assert all(abs(s - _HOUR) < 1 for s in slept)
    assert outcome.stopped_because == "the duration was reached"
    with company.database.session() as session:
        kinds = [
            k
            for (k,) in session.execute(
                sa.text("SELECT kind FROM events WHERE kind LIKE 'service.%' ORDER BY seq")
            )
        ]
    run = [k for k in kinds if k in ("service.started", "service.woke", "service.stopped")]
    assert run[0] == "service.started" and run[-1] == "service.stopped"
    assert run.count("service.woke") == 4


def test_an_interrupt_stops_the_service_and_is_recorded(
    company: Runtime, clock: FrozenClock
) -> None:
    _grant(company, "BTC-USD")
    feed = _GrowingFeed(clock)

    def interrupting(seconds: float) -> None:
        raise KeyboardInterrupt

    outcome = serve(
        company,
        interval_seconds=_HOUR,
        duration_seconds=10 * _HOUR,
        service=_service(company, clock, feed),
        sleeper=interrupting,
    )
    assert len(outcome.wakes) == 1
    assert outcome.stopped_because == "interrupted by the operator"


def test_the_service_cannot_trade_or_grant_itself_anything(
    company: Runtime, clock: FrozenClock
) -> None:
    """Static: nothing under aurelis.service imports a broker or writes a grant
    outside the one method a person calls."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "aurelis" / "service"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not any("trading" in name or "broker" in name for name in names), path.name
    with company.database.session() as session:
        source = pathlib.Path(root / "loop.py").read_text(encoding="utf-8")
        assert ".grant(" not in source, "the loop never grants itself a fetch"
        assert Grants.active(session) == []


# ------------------------------------------------------------ the station


def test_the_service_is_legible_on_the_station(company: Runtime, clock: FrozenClock) -> None:
    from aurelis.station.app import station_app
    from aurelis.station.build import build_sealed

    grant = _grant(company, "BTC-USD")
    feed = _GrowingFeed(clock)
    feed.down = True
    wake = cycle_once(company, service=_service(company, clock, feed))
    page = station_app(company).handle("/service", {}).body.decode()
    assert grant.ref in page and wake.ref in page
    assert "ACTIVE" in page and "OPEN" in page
    assert wake.incidents[0] in page
    html = build_sealed(company, company.settings.workspace / "station.html").path.read_text(
        encoding="utf-8"
    )
    assert "The Service" in html and wake.ref in html
    assert Decimal("0") == Decimal(0)
