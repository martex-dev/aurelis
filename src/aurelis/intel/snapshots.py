"""Ingesting a live feed into something research can be run against twice.

The whole point of this module is one sentence: **an experiment cannot be
reproduced against a moving endpoint.** Every preregistration in this company
locks a spec and every run records a ``data_fingerprint``, and both are
worthless if the bars behind them change between two runs of the same
experiment.

So a fetch is an *event* with a record: what was asked for, from whom, when,
how many bars came back, and the hash of every one of them. After that the
snapshot is immutable — a database trigger refuses to change its digest or its
bars — and :class:`SnapshotSource` serves it to the engine through exactly the
:class:`~aurelis.intel.sources.MarketDataSource` protocol the fixtures use.

The engine cannot tell the difference, and that is deliberate. Real data is not
a different research pipeline; it is the same pipeline with a source that
happens to have come from a market.

What a snapshot honestly is
---------------------------

It is a **recording**, not a live connection. The company has seen a real
market as of the moment it fetched, and nothing here streams, updates or knows
what the price is now. That distinction is on the record and on every report:
``is_live`` says the bars came from a market rather than a generator;
``fetched_at`` says when, and how stale that makes them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from aurelis.core.canonical import sha256_of
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.live import CandleFeed
from aurelis.intel.sources import Bar
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.db.tables import Base
from aurelis.platform.ledger.ledger import Ledger

__all__ = [
    "MarketSnapshot",
    "SnapshotBar",
    "SnapshotSource",
    "Snapshots",
    "latest_snapshot",
]


class MarketSnapshot(Base):
    """One fetch, and everything needed to cite it."""

    __tablename__ = "market_snapshots"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    source: Mapped[str] = mapped_column(sa.String(32), index=True)
    endpoint: Mapped[str] = mapped_column(sa.String(200))
    symbol: Mapped[str] = mapped_column(sa.String(32), index=True)
    interval: Mapped[str] = mapped_column(sa.String(8))

    bars: Mapped[int] = mapped_column()
    first_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    last_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))

    digest: Mapped[str] = mapped_column(sa.String(64), index=True)
    """The hash of every bar in order. What a registration cites, and what
    makes "the same experiment" a checkable statement rather than a hope."""

    is_live: Mapped[bool] = mapped_column(default=True)
    """Whether these bars came from a market rather than a generator. A
    fixture may be ingested the same way for testing, and the two must never
    be told apart by whoever remembers which is which."""

    fetched_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    """When the company saw this. A snapshot is a recording, and how stale it
    is belongs beside it rather than in whoever ran the command."""

    __table_args__ = (
        sa.CheckConstraint("bars > 0", name="ck_snapshot_has_bars"),
        sa.CheckConstraint("length(digest) = 64", name="ck_snapshot_is_hashed"),
    )


class SnapshotBar(Base):
    """One bar of one snapshot. Prices as text, for exactness.

    The same rule as money and rates everywhere else here: a price through a
    binary float could not be hashed reproducibly across machines, and the hash
    is the whole provenance mechanism.
    """

    __tablename__ = "snapshot_bars"

    snapshot_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), primary_key=True
    )
    open: Mapped[str] = mapped_column(sa.String(32))
    high: Mapped[str] = mapped_column(sa.String(32))
    low: Mapped[str] = mapped_column(sa.String(32))
    close: Mapped[str] = mapped_column(sa.String(32))
    volume: Mapped[str] = mapped_column(sa.String(40))


def _digest_of(bars: list[Bar]) -> str:
    return sha256_of({"bars": [bar.as_dict() for bar in bars]})


class Snapshots:
    """Fetching, storing and citing real market data."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def ingest(
        self,
        session: Session,
        feed: CandleFeed,
        *,
        desk: str,
        symbol: str,
        interval: str = "1h",
        bars: int = 2000,
        is_live: bool = True,
        actor: str = Actor.OPERATOR,
        at: dt.datetime | None = None,
    ) -> MarketSnapshot:
        """Fetch once, hash, and store. The only way live data enters.

        Refuses an empty result and refuses a gap-free claim it cannot make:
        the bar count on the record is what actually arrived, not what was
        asked for. A snapshot that quietly reported the requested count would
        make every power calculation downstream of it wrong.
        """
        moment = at or self._clock.now()
        fetched = feed.candles(symbol, interval=interval, bars=bars)
        if not fetched:
            raise IntegrityViolation(
                f"{feed.name} returned no bars for {symbol}; nothing was stored"
            )
        ordered = sorted(fetched, key=lambda bar: bar.timestamp)
        ref = allocate_ref(session, RefKind.SNAPSHOT)
        digest = _digest_of(ordered)

        session.add(
            MarketSnapshot(
                snapshot_id=uuid7(),
                ref=ref,
                desk=desk,
                source=feed.name,
                endpoint=feed.endpoint,
                symbol=symbol,
                interval=interval,
                bars=len(ordered),
                first_at=ordered[0].timestamp,
                last_at=ordered[-1].timestamp,
                digest=digest,
                is_live=is_live,
                fetched_at=moment,
            )
        )
        for bar in ordered:
            session.add(
                SnapshotBar(
                    snapshot_ref=ref,
                    timestamp=bar.timestamp,
                    open=str(bar.open),
                    high=str(bar.high),
                    low=str(bar.low),
                    close=str(bar.close),
                    volume=str(bar.volume),
                )
            )
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.MARKET_SNAPSHOT_INGESTED,
            actor=actor,
            subject=ref,
            payload={
                "desk": desk,
                "source": feed.name,
                "endpoint": feed.endpoint,
                "symbol": symbol,
                "interval": interval,
                "bars": len(ordered),
                "requested": bars,
                "first_at": ordered[0].timestamp.isoformat(),
                "last_at": ordered[-1].timestamp.isoformat(),
                "digest": digest[:16],
                "is_live": is_live,
            },
            at=moment,
        )
        return self.get(session, ref)

    @staticmethod
    def get(session: Session, ref: str) -> MarketSnapshot:
        row = session.execute(
            sa.select(MarketSnapshot).where(MarketSnapshot.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(f"no market snapshot {ref}")
        return row

    @staticmethod
    def bars_of(session: Session, ref: str) -> list[Bar]:
        rows = session.execute(
            sa.select(SnapshotBar)
            .where(SnapshotBar.snapshot_ref == ref)
            .order_by(SnapshotBar.timestamp)
        ).scalars()
        return [
            Bar(
                timestamp=row.timestamp
                if row.timestamp.tzinfo
                else row.timestamp.replace(tzinfo=dt.UTC),
                open=Decimal(row.open),
                high=Decimal(row.high),
                low=Decimal(row.low),
                close=Decimal(row.close),
                volume=Decimal(row.volume),
            )
            for row in rows
        ]

    def verify(self, session: Session, ref: str) -> tuple[bool, str]:
        """Rehash the stored bars against the digest written at ingestion.

        The same standard the artifact store and the event chain are held to.
        A snapshot whose bars were edited after the fact would otherwise be
        cited by every experiment that ran on it, with the citation still
        looking correct.
        """
        row = self.get(session, ref)
        recomputed = _digest_of(self.bars_of(session, ref))
        if recomputed == row.digest:
            return True, f"{ref}: {row.bars} bar(s), digest matches"
        return False, (
            f"{ref}: stored bars hash to {recomputed[:16]}, the record says "
            f"{row.digest[:16]}. Something changed them after ingestion."
        )


def latest_snapshot(
    session: Session, *, desk: str | None = None, live_only: bool = True
) -> MarketSnapshot | None:
    """The most recent snapshot, or ``None``.

    ``None`` rather than an exception: a company with no market data yet is an
    ordinary state, and it is the state the mandate reports on.
    """
    query = sa.select(MarketSnapshot).order_by(
        MarketSnapshot.fetched_at.desc(), MarketSnapshot.ref.desc()
    )
    if desk is not None:
        query = query.where(MarketSnapshot.desk == desk)
    if live_only:
        query = query.where(MarketSnapshot.is_live.is_(True))
    return session.execute(query.limit(1)).scalars().first()


class SnapshotSource:
    """A stored snapshot, served through the ordinary source protocol.

    The engine cannot tell this from a fixture, and must not be able to. Real
    data is not a second research pipeline; it is the same pipeline with a
    source whose bars came from a market.

    ``surviving`` and ``listed_as_of`` both return the one symbol. That is not
    a claim that survivorship cannot bite real data — it is the honest state of
    a single-instrument snapshot, where there is no cross-section to select
    from and therefore nothing for a hindsight universe to quietly drop.
    """

    def __init__(self, session: Session, snapshot: MarketSnapshot) -> None:
        self._bars = Snapshots.bars_of(session, snapshot.ref)
        self.snapshot = snapshot
        self.name = f"{snapshot.source}:{snapshot.ref}"

    def bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        if symbol not in (self.snapshot.symbol, ""):
            raise IntegrityViolation(
                f"{self.name} holds {self.snapshot.symbol}, not {symbol!r}. A "
                "snapshot serves what it recorded and nothing else."
            )
        return self._bars[-limit:] if limit else list(self._bars)

    def symbols(self) -> tuple[str, ...]:
        return (self.snapshot.symbol,)

    def all_symbols(self) -> tuple[str, ...]:
        return (self.snapshot.symbol,)

    def listed_as_of(self, moment: dt.datetime) -> tuple[str, ...]:
        return (self.snapshot.symbol,) if moment >= self.snapshot.first_at else ()

    def surviving(self) -> tuple[str, ...]:
        return (self.snapshot.symbol,)

    def anchor(self) -> dt.datetime:
        return self.snapshot.first_at

    def describe(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.ref,
            "source": self.snapshot.source,
            "symbol": self.snapshot.symbol,
            "interval": self.snapshot.interval,
            "bars": self.snapshot.bars,
            "digest": self.snapshot.digest[:16],
            "is_live": self.snapshot.is_live,
            "fetched_at": self.snapshot.fetched_at.isoformat(),
        }
