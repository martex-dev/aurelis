"""M34 — a mechanism is tested across the universe, not on one chart.

The acceptance criteria, each with a test named after it:

* the universe is ranked by dollar notional, not by units,
* pegged instruments are excluded by their measured range, not by name,
* a universe grant records the rule and the ranking it was drawn from, and is
  as frozen as a typed one,
* a rule that selects nothing is not a grant, and a vendor that is down is an
  error at grant time, not a grant,
* a mechanism stated on one instrument is tested on every instrument granted,
  and none of those is the training occurrence,
* an instrument on two grants is fetched once a wake.

**Nothing here touches the network.** The stats document is a dict; the
recordings are recorded payloads; the catalogue and the book are stand-ins.
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

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.errors import IntegrityViolation
from aurelis.intel.live import CoinbaseCandles, FeedUnavailable
from aurelis.judgement.resolution import resolve_due
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.discovery import propose_mechanism
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.standin import scripted_discovery
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.service.tables import DataGrant
from aurelis.world.derive import derive_price_events
from aurelis.world.liquidity import CoinbaseStats, UniverseRule, rank_universe

_HOUR = 3600
_START = 1_780_000_000


def _day(last: str, volume: str, high: str, low: str) -> dict[str, Any]:
    return {"stats_24hour": {"open": low, "high": high, "low": low, "last": last, "volume": volume}}


_STATS: dict[str, Any] = {
    # 5,000 BTC at 100,000: 500m notional.
    "BTC-USD": _day("100000", "5000", "102000", "98000"),
    # A memecoin with half a trillion units traded: 5m notional.
    "PEPE-USD": _day("0.00001", "500000000000", "0.000011", "0.000009"),
    "ETH-USD": _day("3000", "100000", "3100", "2900"),  # 300m
    # A stablecoin: 200m notional, a tenth of a percent wide all day.
    "USDT-USD": _day("1.0000", "200000000", "1.0005", "0.9995"),
    "SOL-USD": _day("200", "500000", "210", "190"),  # 100m
    "BTC-EUR": _day("90000", "9000", "92000", "88000"),  # not the quote asked for
    "NEW-USD": {"stats_24hour": {"open": "", "high": "", "low": "", "last": "", "volume": ""}},
    "ODD-USD": "not a stats row",
}


class _Stats:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = _STATS if payload is None else payload

    def stats(self) -> dict[str, Any]:
        return self.payload


def _rising(count: int, *, breaks_every: int = 10, base: float = 100.0) -> bytes:
    rows = []
    high = base
    for i in range(count):
        if i % breaks_every == 0:
            high += 5.0
        close = high
        rows.append([_START + i * _HOUR, close - 1, close + 1, close, close, 5.0])
    return json.dumps(list(reversed(rows))).encode()


class _Payload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._data)


class _GrowingFeed:
    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.calls = 0

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        self.calls += 1
        now = int(self.clock.now().timestamp())
        count = max(1, (now - _START) // _HOUR)
        rows = [
            [_START + i * _HOUR, 99.0 + i, 101.0 + i, 100.0 + i, 100.0 + i, 5.0]
            for i in range(count)
        ]
        return io.BytesIO(json.dumps(list(reversed(rows))).encode())


class _NoCatalogue:
    def __init__(self) -> None:
        self.name = "coinbase"
        self.endpoint = "stand-in://catalogue"

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


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 299 * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _grants(company: Runtime) -> list[DataGrant]:
    with company.database.session() as session:
        return list(session.execute(sa.select(DataGrant).order_by(DataGrant.ref)).scalars())


# ------------------------------------------------------------ the ranking


def test_the_universe_is_ranked_by_dollar_notional_not_by_units() -> None:
    drawn = rank_universe(_STATS, UniverseRule(quote="USD", top=10))
    order = [row.symbol for row in drawn.ranked]
    assert order[0] == "BTC-USD", "five thousand bitcoin outrank half a trillion memecoins"
    assert order[-1] == "PEPE-USD"
    assert order.index("ETH-USD") < order.index("SOL-USD")
    assert "BTC-EUR" not in order, "a different quote asset is a different universe"
    assert "NEW-USD" not in order and "ODD-USD" not in order, "no stats, no rank"
    btc = drawn.ranked[0]
    assert btc.notional_24h == Decimal("500000000.00")
    assert btc.range_24h_pct == Decimal("4.0000")


def test_pegged_instruments_are_excluded_by_their_measured_range_not_by_name() -> None:
    drawn = rank_universe(_STATS, UniverseRule(quote="USD", top=3, min_range_pct=Decimal("0.2")))
    assert drawn.chosen == ("BTC-USD", "ETH-USD", "SOL-USD")
    assert drawn.excluded_pegged == ("USDT-USD",), "third by notional, a tenth of a percent wide"
    assert "PEPE-USD" not in drawn.chosen, "below the top, not pegged"
    assert "under 0.2%" in drawn.rule.describe()
    # Loosen the rule and the same instrument is a market again: the exclusion
    # is the rule's measurement, not a list.
    loose = rank_universe(_STATS, UniverseRule(quote="USD", top=3, min_range_pct=Decimal("0.05")))
    assert loose.chosen == ("BTC-USD", "ETH-USD", "USDT-USD")
    assert loose.excluded_pegged == ()


# ------------------------------------------------------------ the grant


def test_a_universe_grant_records_the_rule_and_the_ranking_and_is_as_frozen_as_a_typed_one(
    company: Runtime,
) -> None:
    rule = UniverseRule(quote="USD", top=3)
    with company.database.session() as session:
        row, drawn = company.grants.grant_universe(
            session,
            stats=_Stats(),
            artifacts=company.artifacts,
            rule=rule,
            desk="crypto",
            granted_by="OPERATOR",
            reason="a mechanism is a claim about an event, tested wherever it fires",
        )
        ref, digest = row.ref, row.selection_digest
    grant = _grants(company)[0]
    assert grant.ref == ref
    assert list(grant.instruments) == ["BTC-USD", "ETH-USD", "SOL-USD"] == list(drawn.chosen)
    assert grant.rule == rule.describe() and "top 3" in grant.rule
    assert digest is not None
    record = json.loads(company.artifacts.get(digest))
    assert record["chosen"] == ["BTC-USD", "ETH-USD", "SOL-USD"]
    assert record["excluded_pegged"] == ["USDT-USD"]
    assert [r["symbol"] for r in record["ranked"]][0] == "BTC-USD"

    with company.database.session() as session:
        payload = session.execute(
            sa.text(
                "SELECT payload FROM events WHERE kind = 'service.data_granted' "
                "ORDER BY seq DESC"
            )
        ).scalar_one()
    event = json.loads(payload) if isinstance(payload, str) else payload
    assert event["rule"] == rule.describe() and event["selection"] == digest
    assert event["instruments"] == ["BTC-USD", "ETH-USD", "SOL-USD"]

    # The rule is provenance, and provenance is frozen with the rest.
    for column, value in (("rule", "'top 300 instruments'"), ("selection_digest", "'0'")):
        with (
            company.database.session() as session,
            pytest.raises(IntegrityError, match="cannot be changed"),
        ):
            session.execute(
                sa.text(f"UPDATE data_grants SET {column} = {value} WHERE ref = :r"), {"r": ref}
            )
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="cannot be changed"),
    ):
        session.execute(
            sa.text("UPDATE data_grants SET instruments = '[\"BTC-USD\"]' WHERE ref = :r"),
            {"r": ref},
        )


def test_a_rule_that_selects_nothing_is_not_a_grant_and_a_vendor_down_is_not_one_either(
    company: Runtime,
) -> None:
    only_pegged = {"USDT-USD": _STATS["USDT-USD"], "BTC-EUR": _STATS["BTC-EUR"]}
    with (
        company.database.session() as session,
        pytest.raises(IntegrityViolation, match="selects no instrument"),
    ):
        company.grants.grant_universe(
            session,
            stats=_Stats(only_pegged),
            artifacts=company.artifacts,
            rule=UniverseRule(quote="USD", top=5),
            desk="crypto",
            granted_by="OPERATOR",
            reason="a rule that would grant nothing, on purpose",
        )

    def refused(request: object, timeout: int = 0) -> object:  # noqa: ARG001
        raise OSError("connection refused")

    with (
        company.database.session() as session,
        pytest.raises(FeedUnavailable, match="could not be reached"),
    ):
        company.grants.grant_universe(
            session,
            stats=CoinbaseStats(opener=refused),
            artifacts=company.artifacts,
            rule=UniverseRule(quote="USD", top=5),
            desk="crypto",
            granted_by="OPERATOR",
            reason="a vendor that is down at grant time",
        )
    assert _grants(company) == [], "nothing was granted either time"


# ------------------------------------------------------------ across the universe


def test_a_mechanism_stated_on_one_instrument_is_tested_on_every_instrument_granted(
    settings: Settings, clock: FrozenClock
) -> None:
    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=scripted_discovery)
    )
    built.initialise()
    built.staff()
    try:
        with built.database.session() as session:
            snapshot = built.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Payload(_rising(300)), pause=0),
                desk="crypto",
                symbol="BTC-USD",
                bars=300,
            )
            derive_price_events(session, built.world, snapshot)
            mechanism = propose_mechanism(
                built.provider,
                session,
                built.mechanisms,
                agent_ref=built.roster.by_handle(session, "QUANT").ref,
                trigger_kind="price.range_break",
                second_kind="price.range_break",
                desk="crypto",
                window_hours=48,
                ledger=built.ledger,
            )
            assert mechanism is not None and mechanism.found_on_instrument == "BTC-USD"

        # A second instrument the mechanism has never seen, whose range also
        # breaks; its own most recent break is still inside the horizon.
        with built.database.session() as session:
            other = built.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Payload(_rising(300, base=40.0)), pause=0),
                desk="crypto",
                symbol="ETH-USD",
                bars=300,
            )
            derive_price_events(session, built.world, other)
            run = generate_predictions(session, mechanism, clock=built.clock)
            predictions = list(
                session.execute(
                    sa.select(Thesis).where(Thesis.mechanism_ref == mechanism.ref)
                ).scalars()
            )
        assert run.sealed
        by_instrument = {p.instrument for p in predictions}
        assert by_instrument == {"BTC-USD", "ETH-USD"}, "it fires wherever the event does"
        on_other = [p for p in predictions if p.instrument == "ETH-USD"]
        assert on_other and not any(p.mechanism_training for p in on_other), (
            "nothing on the other instrument is the training occurrence"
        )
        assert all(p.resolves_at > p.sealed_at for p in predictions)

        # And they score, on the other instrument's own recording.
        built.clock.advance(hours=30)
        with built.database.session() as session:
            for symbol, base in (("BTC-USD", 100.0), ("ETH-USD", 40.0)):
                built.snapshots.ingest(
                    session,
                    CoinbaseCandles(opener=_Payload(_rising(360, base=base)), pause=0),
                    desk="crypto",
                    symbol=symbol,
                    bars=360,
                )
            results = resolve_due(session, ledger=built.ledger, clock=built.clock)
            scored_on_other = session.execute(
                sa.select(sa.func.count()).where(
                    Thesis.mechanism_ref == mechanism.ref,
                    Thesis.instrument == "ETH-USD",
                    Thesis.scored_at.is_not(None),
                )
            ).scalar_one()
            status = built.mechanisms.status(session, mechanism.ref)
        assert any(r.scored for r in results)
        assert scored_on_other >= 1
        assert status.scored >= scored_on_other
    finally:
        built.close()


# ------------------------------------------------------------ two grants, one instrument


def test_an_instrument_on_two_grants_is_fetched_once_a_wake(
    company: Runtime, clock: FrozenClock
) -> None:
    with company.database.session() as session:
        for reason in ("the first grant, named by hand", "the second, drawn as a universe"):
            company.grants.grant(
                session,
                source="coinbase",
                desk="crypto",
                instruments=("BTC-USD", "ETH-USD") if "first" in reason else ("BTC-USD",),
                granted_by="OPERATOR",
                reason=reason,
                bars=300,
            )
    feed = _GrowingFeed(clock)
    service = Service(
        company,
        feeds=lambda _grant: CoinbaseCandles(opener=feed, pause=0),
        catalogues=lambda _grant: _NoCatalogue(),
        microstructure=lambda _grant: (_Book(), _Trades()),
        cycles_per_wake=5,
    )
    wake = cycle_once(company, service=service)
    assert len(wake.fetched) == 2, "BTC-USD once and ETH-USD once, not BTC-USD twice"
    assert "1 instrument(s) on more than one grant, fetched once" in wake.note
    with company.database.session() as session:
        symbols = list(
            session.execute(
                sa.text("SELECT symbol FROM market_snapshots ORDER BY symbol")
            ).scalars()
        )
    assert symbols == ["BTC-USD", "ETH-USD"]
    with company.database.session() as session:
        books = session.execute(
            sa.text("SELECT count(*) FROM world_events WHERE kind = 'book.snapshot'")
        ).scalar_one()
    assert books == 2, "and the book was read once per instrument too"
