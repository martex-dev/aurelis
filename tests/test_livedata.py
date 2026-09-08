"""M21 — the two conditions the mandate said were blocked.

M20's standard reported two things no amount of research could satisfy: no desk
had ever seen a market, and nothing wrote a replication record though the table
had existed since M5. These are both, and the standard's own report is what
named them.

**Nothing here touches the network.** The feed is a protocol and every test
passes a recorded payload — the same discipline every other external dependency
in this repository is held to. The one command that reaches a market is
`aurelis data fetch`, and a person types it on purpose.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.core.errors import IntegrityViolation
from aurelis.engines.spec import (
    BacktestSpec,
    DataSpec,
    ExperimentSpec,
    SignalSpec,
    UniverseSpec,
)
from aurelis.intel.live import (
    COINBASE_GRANULARITIES,
    CoinbaseCandles,
    FeedUnavailable,
    interval_seconds,
)
from aurelis.intel.snapshots import (
    MarketSnapshot,
    SnapshotBar,
    SnapshotSource,
    latest_snapshot,
)
from aurelis.mandate.standard import STANDARD
from aurelis.research.replication import (
    ReplicationOutcome,
    Variation,
    replications_of,
    vary,
)
from aurelis.research.states import RegistrationKind
from aurelis.research.tables import Replication
from aurelis.runtime import Runtime

_HOUR = 3600
_START = 1_780_000_000


def _rows(count: int) -> list[list[float]]:
    """Vendor-shaped candles: [time, low, high, open, close, volume].

    Newest first, which is the order the vendor actually returns and the order
    the adapter has to cope with.
    """
    return [
        [
            _START + index * _HOUR,
            100.0 + index,  # low
            110.0 + index,  # high
            105.0 + index,  # open
            106.0 + index,  # close
            7.5,
        ]
        for index in reversed(range(count))
    ]


class _Recorded:
    """A recorded response. The tests' entire contact with a vendor."""

    def __init__(self, rows: list[list[float]] | Exception) -> None:
        self._rows = rows
        self.calls = 0

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        self.calls += 1
        if isinstance(self._rows, Exception):
            raise self._rows
        return io.BytesIO(json.dumps(self._rows).encode())


@pytest.fixture
def company(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    built = Runtime.build(settings, clock=clock)
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


# ------------------------------------------------------------- the vendor


def test_the_vendor_column_order_is_not_ohlcv() -> None:
    """[time, low, high, open, close, volume].

    Low and high come before open and close, which is not what the word OHLCV
    implies and not the order anything else here uses. Reading it as OHLC would
    swap the open with the low on every bar — prices that still look like
    prices, hash reproducibly, and are wrong.
    """
    feed = CoinbaseCandles(opener=_Recorded(_rows(1)))
    bar = feed.candles("BTC-USD", interval="1h", bars=1)[0]
    assert bar.low == Decimal("100.0")
    assert bar.high == Decimal("110.0")
    assert bar.open == Decimal("105.0")
    assert bar.close == Decimal("106.0")


def test_bars_come_back_oldest_first_however_the_vendor_ordered_them() -> None:
    feed = CoinbaseCandles(opener=_Recorded(_rows(5)))
    bars = feed.candles("BTC-USD", interval="1h", bars=5)
    assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)
    assert all(b.timestamp.tzinfo is dt.UTC for b in bars)


def test_an_interval_the_vendor_does_not_serve_is_refused() -> None:
    """Guessing a granularity would return bars of the wrong width under the
    right label, and no fingerprint would catch it — the hash would faithfully
    record the wrong data."""
    assert interval_seconds("1h") == 3600
    with pytest.raises(IntegrityViolation, match="no vendor granularity"):
        interval_seconds("4h")
    assert "4h" not in COINBASE_GRANULARITIES


def test_an_unreachable_vendor_is_a_state_not_a_crash() -> None:
    feed = CoinbaseCandles(opener=_Recorded(OSError("connection reset")))
    with pytest.raises(FeedUnavailable, match="Nothing was stored"):
        feed.candles("BTC-USD", interval="1h", bars=10)


# ------------------------------------------------------- the frozen snapshot


def test_a_fetch_is_recorded_hashed_and_verifiable(company: Runtime) -> None:
    """An experiment cannot be reproduced against a moving endpoint, so live
    data enters as a recording and research reads the recording."""
    feed = CoinbaseCandles(opener=_Recorded(_rows(120)))
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session, feed, desk="crypto", symbol="BTC-USD", bars=120
        )
        ok, detail = company.snapshots.verify(session, snapshot.ref)
        bars = company.snapshots.bars_of(session, snapshot.ref)

    assert snapshot.bars == 120 == len(bars)
    assert snapshot.is_live
    assert len(snapshot.digest) == 64
    assert ok, detail
    assert snapshot.first_at < snapshot.last_at


def test_an_edited_snapshot_stops_verifying(company: Runtime) -> None:
    """The same standard the artifact store and the event chain are held to.

    Without it, every experiment that cited the snapshot would keep citing it
    and the citation would still look correct.
    """
    feed = CoinbaseCandles(opener=_Recorded(_rows(30)))
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session, feed, desk="crypto", symbol="BTC-USD", bars=30
        )
        ref = snapshot.ref

    with company.database.session() as session:
        session.execute(
            sa.update(SnapshotBar)
            .where(SnapshotBar.snapshot_ref == ref)
            .where(SnapshotBar.timestamp == snapshot.last_at)
            .values(close="999999")
        )
        session.flush()
        ok, detail = company.snapshots.verify(session, ref)

    assert not ok
    assert "changed them after ingestion" in detail


def test_the_record_says_what_arrived_not_what_was_asked_for(
    company: Runtime,
) -> None:
    """A snapshot that reported the requested count would make every power
    calculation downstream of it wrong."""
    feed = CoinbaseCandles(opener=_Recorded(_rows(40)))
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session, feed, desk="crypto", symbol="BTC-USD", bars=5000
        )
    assert snapshot.bars == 40


def test_a_snapshot_serves_the_ordinary_source_protocol(company: Runtime) -> None:
    """The engine cannot tell this from a fixture, and must not be able to.
    Real data is not a second research pipeline."""
    feed = CoinbaseCandles(opener=_Recorded(_rows(200)))
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session, feed, desk="crypto", symbol="BTC-USD", bars=200
        )
        source = SnapshotSource(session, snapshot)

    assert source.symbols() == ("BTC-USD",)
    assert source.surviving() == ("BTC-USD",)
    assert len(source.bars("BTC-USD", limit=50)) == 50
    assert source.anchor() == snapshot.first_at
    assert source.describe()["is_live"] is True

    with pytest.raises(IntegrityViolation, match="holds BTC-USD"):
        source.bars("ETH-USD", limit=10)


def test_the_mandate_reads_the_data_rather_than_a_flag(company: Runtime) -> None:
    """The condition asks whether a real market entered the record, so it reads
    the record. A boolean on a desk opening is whatever the code that wrote it
    believed."""
    live = next(c for c in STANDARD if c.key == "live_data")
    assert not live.blocked, "M21 unblocked it"

    with company.database.session() as session:
        met, reading = live.check(session)
        assert not met
        assert "no live market snapshot" in reading

        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_rows(60))),
            desk="crypto",
            symbol="BTC-USD",
            bars=60,
        )
        met, reading = live.check(session)

    assert met
    assert "BTC-USD" in reading and "coinbase" in reading


def test_an_ingested_fixture_is_not_counted_as_a_market(company: Runtime) -> None:
    """The two must never be told apart by whoever remembers which is which."""
    live = next(c for c in STANDARD if c.key == "live_data")
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_rows(20))),
            desk="crypto",
            symbol="BTC-USD",
            bars=20,
            is_live=False,
        )
        met, _ = live.check(session)
        assert not met
        assert latest_snapshot(session, live_only=True) is None
        assert latest_snapshot(session, live_only=False) is not None


def test_a_snapshot_needs_bars(company: Runtime) -> None:
    with company.database.session() as session:
        with pytest.raises(FeedUnavailable):
            company.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Recorded([])),
                desk="crypto",
                symbol="BTC-USD",
                bars=10,
            )
        assert not session.execute(sa.select(MarketSnapshot)).scalars().all()


# ------------------------------------------------------------ replication


def _registered(company: Runtime, *, bars: int = 600) -> str:
    spec = ExperimentSpec(
        engine="local",
        universe=UniverseSpec(desk="crypto", symbols=(), point_in_time=True),
        data=DataSpec(source="fixture", bars=bars, interval="1h"),
        signal=SignalSpec(kind="momentum", lookback=24),
        backtest=BacktestSpec(),
        metrics=("total_return", "sharpe", "max_drawdown"),
    )
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        gov = company.roster.by_handle(session, "GOV").ref
        hypothesis = company.research.propose(
            session,
            claim="momentum earns a positive Sharpe",
            author=quant,
            minimum_effect=Decimal("0.02"),
            primary_metric="sharpe",
            family="replication.demo",
        )
        company.research.screen(session, hypothesis.ref)
        registration = company.research.register(
            session,
            hypothesis_ref=hypothesis.ref,
            spec=spec,
            pass_criteria=[
                {"metric": "sharpe", "comparison": "gt", "value": "0", "on": "low"}
            ],
            registrar=gov,
            kind=RegistrationKind.CONFIRMATORY,
        )
        return registration.ref


def test_a_replication_must_vary_something() -> None:
    """Every engine here is deterministic, so re-running the identical
    specification returns the identical number. Learning that determinism holds
    is not evidence about a market."""
    spec = ExperimentSpec(
        engine="local",
        universe=UniverseSpec(desk="crypto", symbols=(), point_in_time=True),
        data=DataSpec(source="fixture", bars=600),
        signal=SignalSpec(kind="momentum", lookback=24),
    )
    for variation in Variation:
        assert vary(spec, variation).digest() != spec.digest()

    assert vary(spec, Variation.SEED).seed == spec.seed + 1
    assert vary(spec, Variation.SHORTER_WINDOW).data.bars < spec.data.bars
    assert vary(spec, Variation.EARLIER_WINDOW).data.bars > spec.data.bars


def test_a_variation_never_touches_the_rule() -> None:
    """A replication that changed the signal would be testing a different
    rule, and the word would be doing work the evidence does not."""
    spec = ExperimentSpec(
        engine="local",
        universe=UniverseSpec(desk="crypto", symbols=(), point_in_time=True),
        data=DataSpec(source="fixture", bars=600),
        signal=SignalSpec(kind="momentum", lookback=24, threshold=Decimal("0.01")),
    )
    for variation in Variation:
        varied = vary(spec, variation)
        assert varied.signal == spec.signal
        assert varied.universe == spec.universe
        assert varied.backtest.costs == spec.backtest.costs


def test_a_replication_is_written_down_with_what_it_varied(
    company: Runtime,
) -> None:
    """The table has existed since M5 and nothing ever wrote a row into it."""
    registration = _registered(company)
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        report = company.replications.replicate(
            session,
            registration_ref=registration,
            variation=Variation.SEED,
            author=quant,
        )
        rows = replications_of(session, registration)

    assert len(rows) == 1
    assert rows[0].ref == report.ref
    assert rows[0].outcome == report.outcome.value
    assert "seed" in rows[0].varied
    assert "->" in rows[0].varied, "it names both spec digests"


def test_replicating_a_result_that_never_settled_holds_nothing(
    company: Runtime,
) -> None:
    """The bug the first run of this module found.

    Three variations of an underpowered registration all came back
    underpowered, the verdicts matched, and every one was recorded as `held` —
    which `aurelis.memory.confidence` counts as evidence. Same verdict is not
    the same as a result surviving.
    """
    registration = _registered(company)
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        reports = [
            company.replications.replicate(
                session,
                registration_ref=registration,
                variation=variation,
                author=quant,
            )
            for variation in Variation
        ]

    assert all(r.original_verdict == "underpowered" for r in reports)
    assert all(r.outcome is ReplicationOutcome.NOTHING_TO_REPLICATE for r in reports)
    assert not any(r.held for r in reports)
    assert not any(r.settled_anything for r in reports)

    with company.database.session() as session:
        held = session.execute(
            sa.select(sa.func.count())
            .select_from(Replication)
            .where(Replication.outcome == "held")
        ).scalar_one()
    assert held == 0, "confidence must not accumulate from replications of nothing"


def test_an_unlocked_registration_cannot_be_replicated(company: Runtime) -> None:
    """Its criteria could still change, and a replication inherits them."""
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        with pytest.raises(IntegrityViolation, match="no registration"):
            company.replications.replicate(
                session,
                registration_ref="REG-9999",
                variation=Variation.SEED,
                author=quant,
            )


def test_the_mandate_now_sees_replications(company: Runtime) -> None:
    """Unblocked, and still unmet until one actually holds — which is the
    honest state of a company whose only registration was underpowered."""
    replicated = next(c for c in STANDARD if c.key == "replicated")
    assert not replicated.blocked, "M21 unblocked it"

    registration = _registered(company)
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        company.replications.replicate(
            session,
            registration_ref=registration,
            variation=Variation.SEED,
            author=quant,
        )
        met, reading = replicated.check(session)

    assert not met
    assert "nothing_to_replicate" in reading
