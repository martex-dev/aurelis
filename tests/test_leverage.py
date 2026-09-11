"""M35 — the leverage the agents keep citing enters the stream.

The acceptance criteria, each with a test named after it:

* funding and open interest are recorded as events on the spot instrument,
  with the perpetual and the venue named and the perpetual related to it,
* extreme funding and an open-interest surge (or purge) are derived, and each
  carries the threshold that produced it,
* the same settlement read twice is one event,
* a symbol without a perpetual is counted, not an incident; a venue that is
  down is one incident and the wake continues,
* a leverage grant reads leverage and cannot fetch bars,
* a mechanism fires on extreme funding and seals against the spot close,
* the judge is shown the leverage.

**Nothing here touches the network.** The venue is a router over recorded
payloads keyed by the endpoint asked.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.errors import IntegrityViolation
from aurelis.intel.leverage import (
    FUNDING_EXTREME,
    OI_SURGE,
    BybitLeverage,
    perp_for,
    record_leverage,
)
from aurelis.intel.live import CoinbaseCandles
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.service.grants import feed_for
from aurelis.service.loop import Service, cycle_once
from aurelis.world.store import World
from aurelis.world.tables import Relation

_HOUR = 3600
_START = 1_780_000_000


def _ms(hours: int) -> str:
    return str((_START + hours * _HOUR) * 1000)


class _Bybit:
    """The venue: three endpoints, answered from what the test set up."""

    def __init__(
        self,
        *,
        listed: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
        rate: str = "0.0001",
        funding_at_hours: int = 192,
        oi_now: str = "1000",
        oi_then: str = "950",
        down: bool = False,
    ) -> None:
        self.listed = listed
        self.rate = rate
        self.funding_at_hours = funding_at_hours
        self.oi_now = oi_now
        self.oi_then = oi_then
        self.down = down
        self.calls: list[str] = []

    def __call__(self, request: Any, timeout: int = 0) -> object:  # noqa: ARG002
        url = str(request.full_url)
        self.calls.append(url)
        if self.down:
            raise OSError("connection refused")
        if "instruments-info" in url:
            rows: list[dict[str, Any]] = [
                {"symbol": s, "quoteCoin": "USDT", "status": "Trading"} for s in self.listed
            ]
        elif "funding/history" in url:
            symbol = url.split("symbol=")[1].split("&")[0]
            rows = [
                {
                    "symbol": symbol,
                    "fundingRate": self.rate,
                    "fundingRateTimestamp": _ms(self.funding_at_hours),
                },
                {
                    "symbol": symbol,
                    "fundingRate": "0.0001",
                    "fundingRateTimestamp": _ms(self.funding_at_hours - 8),
                },
            ]
        elif "open-interest" in url:
            rows = [
                {
                    "openInterest": self.oi_then if i == 24 else self.oi_now,
                    "timestamp": _ms(200 - i),
                }
                for i in range(25)
            ]
        else:
            raise AssertionError(url)
        payload = {"retCode": 0, "retMsg": "OK", "result": {"list": rows}}
        return io.BytesIO(json.dumps(payload).encode())


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


def _events(company: Runtime, symbol: str = "BTC-USD") -> dict[str, dict[str, Any]]:
    with company.database.session() as session:
        rows = World.events_for(session, entity_kind="instrument", entity_key=symbol)
    return {row.kind: dict(row.payload) for row in rows}


# ------------------------------------------------------------ the readings


def test_funding_and_open_interest_are_recorded_on_the_spot_instrument_with_the_perp_named(
    company: Runtime, clock: FrozenClock
) -> None:
    venue = _Bybit()
    with company.database.session() as session:
        reading, new = record_leverage(
            session,
            company.world,
            company.artifacts,
            symbol="BTC-USD",
            feed=BybitLeverage(opener=venue),
            clock=clock,
        )
    assert perp_for("BTC-USD") == "BTCUSDT" and reading.perp == "BTCUSDT"
    assert new == 2, "funding and open interest; nothing extreme to derive"
    events = _events(company)
    assert set(events) == {"leverage.funding", "leverage.open_interest"}
    funding = events["leverage.funding"]
    assert funding["venue"] == "bybit" and funding["perp"] == "BTCUSDT"
    assert funding["rate"] == "0.00010000"
    assert funding["annualised_pct"] == "10.95", "a basis point per eight hours, three a day"
    oi = events["leverage.open_interest"]
    assert oi["open_interest"] == "1000.000" and oi["change_24h_pct"] == "5.26"
    assert reading.funding_at == dt.datetime.fromtimestamp(_START + 192 * _HOUR, tz=dt.UTC)

    with company.database.session() as session:
        relation = session.execute(
            sa.select(Relation).where(
                Relation.subject_key == "BTCUSDT", Relation.kind == "derivative_of"
            )
        ).scalar_one()
        assert relation.object_key == "BTC-USD"
        raw = json.loads(company.artifacts.get(reading.raw_digest))
    assert raw["perp"] == "BTCUSDT" and len(raw["oi"]) == 25
    assert all("BTCUSDT" in url for url in venue.calls[:2]), "the perpetual was asked, by name"


def test_extreme_funding_and_an_open_interest_surge_are_derived_with_their_thresholds(
    company: Runtime, clock: FrozenClock
) -> None:
    with company.database.session() as session:
        _, new = record_leverage(
            session,
            company.world,
            company.artifacts,
            symbol="BTC-USD",
            feed=BybitLeverage(opener=_Bybit(rate="0.0008", oi_then="900")),
            clock=clock,
        )
    assert new == 4
    events = _events(company)
    assert events["funding.extreme_positive"]["threshold"] == str(FUNDING_EXTREME)
    assert events["funding.extreme_positive"]["rate"] == "0.00080000"
    assert events["oi.surge"]["change_24h_pct"] == "11.11"
    assert events["oi.surge"]["threshold"] == str(OI_SURGE)

    with company.database.session() as session:
        record_leverage(
            session,
            company.world,
            company.artifacts,
            symbol="ETH-USD",
            feed=BybitLeverage(opener=_Bybit(rate="-0.0008", oi_then="1200")),
            clock=clock,
        )
    other = _events(company, "ETH-USD")
    assert other["funding.extreme_negative"]["threshold"] == str(-FUNDING_EXTREME)
    assert other["oi.purge"]["change_24h_pct"] == "-16.67"
    assert "funding.extreme_positive" not in other and "oi.surge" not in other


def test_the_same_settlement_read_twice_is_one_event(company: Runtime, clock: FrozenClock) -> None:
    for expected in (2, 0):
        with company.database.session() as session:
            _, new = record_leverage(
                session,
                company.world,
                company.artifacts,
                symbol="BTC-USD",
                feed=BybitLeverage(opener=_Bybit()),
                clock=clock,
            )
        assert new == expected
    with company.database.session() as session:
        count = session.execute(
            sa.text("SELECT count(*) FROM world_events WHERE kind = 'leverage.funding'")
        ).scalar_one()
    assert count == 1


# ------------------------------------------------------------ under the service


def _leverage_grant(company: Runtime, *instruments: str) -> None:
    with company.database.session() as session:
        company.grants.grant(
            session,
            source="bybit",
            desk="crypto",
            instruments=instruments,
            granted_by="OPERATOR",
            reason="the leverage the agents keep citing, on the record",
        )


def test_a_symbol_without_a_perp_is_counted_not_an_incident_and_a_venue_down_is_one(
    company: Runtime,
) -> None:
    _leverage_grant(company, "BTC-USD", "VTHO-USD")
    venue = _Bybit(listed=("BTCUSDT",))
    service = Service(
        company, leverage=lambda _grant: BybitLeverage(opener=venue), cycles_per_wake=2
    )
    wake = cycle_once(company, service=service)
    assert wake.fetched == (), "a leverage grant fetches no bars"
    assert wake.incidents == ()
    assert "leverage: 1 reading(s), 2 event(s), 1 without a perpetual" in wake.note
    assert sum(1 for url in venue.calls if "instruments-info" in url) == 1, "listed once a wake"
    assert not any("VTHOUSDT" in url for url in venue.calls)

    venue.down = True
    again = cycle_once(company, service=service)
    assert len(again.incidents) == 1
    with company.database.session() as session:
        alert = session.execute(
            sa.text("SELECT source, severity FROM alerts WHERE ref = :r"), {"r": again.incidents[0]}
        ).one()
    assert alert == ("service.leverage", "warning")
    assert again.run_ref is not None, "and the loop still ran"


def test_a_leverage_grant_reads_leverage_and_cannot_fetch_bars(company: Runtime) -> None:
    _leverage_grant(company, "BTC-USD")
    with company.database.session() as session:
        grant = company.grants.active(session)[0]
        assert grant.is_leverage and grant.is_live
        with pytest.raises(IntegrityViolation, match="no feed for source 'bybit'"):
            feed_for(grant)
        with pytest.raises(IntegrityViolation, match="not a vendor"):
            company.grants.grant(
                session,
                source="deribit",
                desk="crypto",
                instruments=("BTC-USD",),
                granted_by="OPERATOR",
                reason="a venue nobody wired, refused at the grant",
            )


# ------------------------------------------------------------ mechanisms and judges


def test_a_mechanism_fires_on_extreme_funding_and_seals_against_the_spot_close(
    company: Runtime, clock: FrozenClock
) -> None:
    from aurelis.mechanism.predictions import generate_predictions

    rows = [[_START + i * _HOUR, 99.0, 101.0, 100.0, 100.0 + i, 5.0] for i in range(201)]
    clock.set(dt.datetime.fromtimestamp(_START + 200 * _HOUR, tz=dt.UTC))
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Json(list(reversed(rows))), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=201,
        )
        # The settlement at the last bar's instant: its horizon is still ahead.
        record_leverage(
            session,
            company.world,
            company.artifacts,
            symbol="BTC-USD",
            feed=BybitLeverage(opener=_Bybit(rate="0.0009", funding_at_hours=200)),
            clock=clock,
        )
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="crowded longs pay to stay and get flushed",
            trigger_kind="funding.extreme_positive",
            desk="crypto",
            horizon_hours=6,
            direction="down",
            confidence=Decimal("0.6"),
            why="longs paying five basis points a settlement are crowded; a dip liquidates them.",
            other_side="the late longs paying the funding, who are the forced sellers on the dip.",
            decay="it fades as funding arbitrage caps the rate, within a quarter.",
            origin="invented",
            found_on_instrument="BTC-USD",
            found_on_event="test",
            model="test",
        )
        run = generate_predictions(session, mechanism, clock=clock)
        thesis = session.execute(
            sa.text(
                "SELECT instrument, direction, reference_close FROM theses WHERE mechanism_ref = :m"
            ),
            {"m": mechanism.ref},
        ).one()
    assert len(run.sealed) == 1
    assert thesis[0] == "BTC-USD" and thesis[1] == "down"
    assert Decimal(thesis[2]) == Decimal("300"), "the spot close at the settlement, not a perp mark"


def test_the_judge_is_shown_the_leverage(company: Runtime, clock: FrozenClock) -> None:
    from aurelis.judgement.seat import _recent_events

    with company.database.session() as session:
        record_leverage(
            session,
            company.world,
            company.artifacts,
            symbol="BTC-USD",
            feed=BybitLeverage(opener=_Bybit(rate="0.0008")),
            clock=clock,
        )
        lines = _recent_events(session, "BTC-USD")
    kinds = [line.split(" ")[1].rstrip(":") for line in lines]
    assert "leverage.funding" in kinds and "funding.extreme_positive" in kinds
    funding_line = next(line for line in lines if "leverage.funding" in line)
    assert "rate 0.00080000" in funding_line and "perp BTCUSDT" in funding_line


class _Json:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(json.dumps(self.payload).encode())
