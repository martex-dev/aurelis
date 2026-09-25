"""M52 — the station shows the company at work, read off the ledger.

The operator's screenshot showed every room IDLE while the agents sealed
twenty views an hour: the plates read ``agents.state``, which the service's
seats never set.

* a room is working when one of its agents acted in the last ten minutes,
  whatever its state column says, and only that many figures move,
* a wake is in progress while recordings or model calls follow the last
  finished wake, and between wakes otherwise,
* the feed says what each decision was, in a line from its own payload, and
  leaves out the recordings and model calls it counts instead,
* the facility serves its changing part alone at ``/now`` for the page to
  refresh in place, and the live stream carries each event's line,
* a coin toss, 0.5 or 50%, is a figure every agent may name.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from aurelis.agents.interpret import unsourced_numerals
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import EventKind
from aurelis.org.departments import Department
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.station import projections as proj
from aurelis.station.activity import activity, describe, feed, wake_state
from aurelis.station.app import station_app

_NOW = dt.datetime(2026, 9, 25, 14, 0, tzinfo=dt.UTC)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(_NOW)


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _act(
    company: Runtime,
    handle: str,
    kind: EventKind,
    *,
    minutes_ago: float,
    subject: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    with company.database.session() as session:
        ref = company.roster.by_handle(session, handle).ref if handle != "SERVICE" else "SERVICE"
        company.ledger.append(
            session,
            kind=kind,
            actor=ref,
            subject=subject,
            payload=payload or {},
            at=_NOW - dt.timedelta(minutes=minutes_ago),
        )
    return ref


def test_a_room_is_working_when_an_agent_in_it_acted_in_the_last_ten_minutes(
    company: Runtime,
) -> None:
    _act(company, "QUANT", EventKind.MODEL_CALLED, minutes_ago=3, payload={"model": "m"})
    _act(company, "INTEL", EventKind.BRAIN_NOTED, minutes_ago=45, payload={"text": "a note"})
    with company.database.session() as session:
        rooms = proj.room_statuses(session, _NOW)
        acts = activity(session, _NOW)
    research = rooms[Department.QUANTITATIVE_RESEARCH]
    intelligence = rooms[Department.MARKET_INTELLIGENCE]
    assert research.plate == "WORKING" and research.working.value == 1
    assert "just now" not in research.last_active and research.last_active == "3m ago"
    assert intelligence.plate == "IDLE" and intelligence.last_active == "45m ago"
    assert intelligence.acts_last_hour == 1
    assert [a.handle for a in acts.values() if a.working(_NOW)] == ["QUANT"]
    with company.database.session() as session:
        later = proj.room_statuses(session, _NOW + dt.timedelta(minutes=11))
    assert later[Department.QUANTITATIVE_RESEARCH].plate == "IDLE", "ten minutes, then idle"


def test_a_wake_is_in_progress_until_it_is_recorded_as_finished(company: Runtime) -> None:
    with company.database.session() as session:
        assert wake_state(session, _NOW).headline(_NOW) == "The service has not woken yet."
    _act(
        company,
        "SERVICE",
        EventKind.SERVICE_WOKE,
        minutes_ago=50,
        subject="WAKE-0001",
        payload={"fetched": ["SNP-0001"]},
    )
    _act(
        company,
        "SERVICE",
        EventKind.MARKET_SNAPSHOT_INGESTED,
        minutes_ago=8,
        subject="SNP-0002",
        payload={"symbol": "BTC-USD", "bars": 400, "source": "coinbase"},
    )
    _act(company, "QUANT", EventKind.MODEL_CALLED, minutes_ago=2, payload={"model": "m"})
    _act(
        company,
        "QUANT",
        EventKind.THESIS_SEALED,
        minutes_ago=1,
        subject="THS-0001",
        payload={
            "instrument": "BTC-USD",
            "direction": "up",
            "horizon_hours": 6,
            "confidence": "0.55",
        },
    )
    with company.database.session() as session:
        wake = wake_state(session, _NOW)
    assert wake.in_progress and wake.calls_this_wake == 1
    assert wake.this_wake["judgement.thesis_sealed"] == 1
    assert wake.headline(_NOW) == "A wake is in progress, started 8m ago: 1 model call(s) so far."


def test_the_feed_says_what_each_decision_was_and_leaves_out_the_heartbeat(
    company: Runtime,
) -> None:
    _act(company, "QUANT", EventKind.MODEL_CALLED, minutes_ago=3, payload={"model": "m"})
    _act(
        company,
        "SERVICE",
        EventKind.MARKET_SNAPSHOT_INGESTED,
        minutes_ago=3,
        payload={"symbol": "BTC-USD"},
    )
    _act(
        company,
        "QUANT",
        EventKind.THESIS_SEALED,
        minutes_ago=2,
        subject="THS-0009",
        payload={
            "instrument": "SOL-USD",
            "direction": "down",
            "horizon_hours": 6,
            "confidence": "0.53",
        },
    )
    _act(
        company,
        "INTEL",
        EventKind.THESIS_DECLINED,
        minutes_ago=1,
        payload={"stage": "market", "reasoning": "nothing here has a dated catalyst"},
    )
    with company.database.session() as session:
        lines = [(f.who, f.line, f.href) for f in feed(session, limit=10)]
    assert lines[:2] == [
        ("INTEL", "declined (no market): nothing here has a dated catalyst", lines[0][2]),
        ("QUANT", "sealed a view: SOL-USD down over 6h at 0.53 (THS-0009)", "/thesis/THS-0009"),
    ]
    assert all("thought" not in line and "recorded" not in line for _, line, _ in lines)
    assert (
        describe(
            "judgement.thesis_scored",
            "THS-1",
            {
                "agent": "AG-0005",
                "instrument": "ONDO-USD",
                "direction": "up",
                "hit": True,
                "brier": "0.2209",
            },
        )
        == "AG-0005's view on ONDO-USD (up) was right, Brier 0.2209 (THS-1)"
    )


def test_the_facility_refreshes_in_place_and_the_stream_carries_each_line(
    company: Runtime,
) -> None:
    _act(
        company,
        "QUANT",
        EventKind.THESIS_SEALED,
        minutes_ago=2,
        subject="THS-0009",
        payload={
            "instrument": "SOL-USD",
            "direction": "down",
            "horizon_hours": 6,
            "confidence": "0.53",
        },
    )
    app = station_app(company)
    home = app.handle("/", {}).body.decode()
    now = app.handle("/now", {}).body.decode()
    assert "id='now'" in home and "id='feed'" in home and 'fetch("/now")' in home
    assert "<html" not in now and "Who is doing what" in now and "views sealed" in now
    assert "sealed a view: SOL-USD down over 6h at 0.53" in home
    (entry,) = [e for e in app.events_since(0) if e["kind"] == "judgement.thesis_sealed"]
    assert entry["listed"] and entry["who"] == "QUANT"
    assert entry["line"] == "sealed a view: SOL-USD down over 6h at 0.53 (THS-0009)"


def test_a_coin_toss_is_a_figure_every_agent_may_name() -> None:
    assert unsourced_numerals("no better than 0.5, a 50% call", set()) == []
    assert unsourced_numerals("at 0.57 over 50 bars", set()) == ["0.57", "50"]
