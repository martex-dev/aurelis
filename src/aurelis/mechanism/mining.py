"""Mining the event stream for conjunctions worth bringing to an agent.

The discovery-driven path the brief describes: enumerate the ordered pairs of
event kinds that co-occur on the same entity inside a window, count them, and
rank them. This produces a list of *conjunctions* and, as the brief says, an
enormous quantity of garbage — which is why it is a list handed to an agent
that must state a mechanism, not a discovery. Deterministic and in software;
no model call.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.world.store import World
from aurelis.world.tables import WorldEvent

__all__ = [
    "READINGS",
    "Effect",
    "MinedPair",
    "effect_of",
    "effect_over",
    "is_reading",
    "mine_pairs",
]

READINGS: frozenset[str] = frozenset(
    {
        "listing.seen",
        "book.snapshot",
        "flow.trades",
        "leverage.funding",
        "leverage.open_interest",
    }
)
"""Kinds the service records as a *reading* on every wake for every followed
instrument, rather than because something happened: the catalogue sighting,
the book snapshot, the hour's trades, the funding rate and the open interest.
A reading co-occurs with everything, so a pair built on one fires on every
bar, and its in-sample "effect" is only the period the reading has been
recorded for. The first live mechanism stated on one (trades followed by an
open-interest reading, 676 predictions in a day, six right of the first
hundred and four) is why this set exists. Derived kinds -- ``book.bid_heavy``,
``funding.extreme_*``, ``oi.surge`` -- are events and stay in."""


def is_reading(kind: str | None) -> bool:
    """Whether a kind is a reading the service takes every wake, not an event."""
    return bool(kind) and kind in READINGS


@dataclass(frozen=True, slots=True)
class MinedPair:
    first: str
    second: str
    count: int
    instruments: int

    def describe(self) -> str:
        return f"{self.first} then {self.second}: {self.count} on {self.instruments} instrument(s)"


def mine_pairs(
    session: Session, *, within: dt.timedelta, min_count: int = 3, limit: int = 20
) -> list[MinedPair]:
    """Every ordered pair of kinds that co-occurs at least ``min_count`` times.

    Ranked by count. A pair of the same kind (a break followed by a break) is
    a legitimate continuation pattern and is included.
    """
    kinds = [
        str(k)
        for (k,) in session.execute(sa.select(WorldEvent.kind).distinct().order_by(WorldEvent.kind))
        if not is_reading(str(k))
    ]
    out: list[MinedPair] = []
    for first in kinds:
        for second in kinds:
            pairs = World.co_occurrences(
                session, first_kind=first, second_kind=second, within=within, limit=10_000
            )
            # A pair of the same event on itself at the same instant is not a
            # conjunction; require the second to follow.
            pairs = [p for p in pairs if p.second.digest != p.first.digest]
            if len(pairs) < min_count:
                continue
            out.append(MinedPair(first, second, len(pairs), len({p.entity_key for p in pairs})))
    out.sort(key=lambda p: (-p.count, p.first, p.second))
    return out[:limit]


@dataclass(frozen=True, slots=True)
class Effect:
    """What followed a trigger, in sample, against what follows any bar.

    In sample on purpose and labelled so everywhere it is shown: this is the
    evidence the mining found, the thing that prompts the question. It is not
    the test. The test is the out-of-sample predictions a stated mechanism
    seals as the trigger fires again.
    """

    trigger: str
    horizon_hours: int
    n: int
    mean_return_after: Decimal
    """Mean percentage change of the close ``h`` bars after a trigger."""

    up_rate_after: Decimal
    unconditional_mean_return: Decimal
    unconditional_up_rate: Decimal
    since: dt.datetime | None = None
    """The instant of the earliest occurrence. The unconditional figures are
    over the bars from here on, not the whole recording: a kind recorded only
    since Thursday, compared against every bar since June, would show the
    effect of Thursday's weather, not of the kind."""

    @property
    def lift(self) -> Decimal:
        return (self.up_rate_after - self.unconditional_up_rate).quantize(Decimal("0.0001"))

    def describe(self) -> str:
        span = f" since {self.since:%Y-%m-%d %H:%M}" if self.since is not None else ""
        return (
            f"after {self.trigger}, {self.horizon_hours}h later: n {self.n}, "
            f"mean {self.mean_return_after}%, up {self.up_rate_after}; any bar{span}: "
            f"mean {self.unconditional_mean_return}%, up {self.unconditional_up_rate}"
        )


def effect_of(
    session: Session, *, trigger: str, horizon_hours: int, limit: int = 2000
) -> Effect | None:
    """The in-sample effect of a trigger over a horizon, from the recordings.

    For every trigger event with a recording that covers both its instant and
    the horizon after it, the close ``h`` bars later is compared with the
    close at the trigger. The unconditional figures are over every bar of the
    same recordings, so the two columns are computed on the same data.
    ``None`` when no occurrence can be settled.
    """
    events = list(
        session.execute(
            sa.select(WorldEvent)
            .where(WorldEvent.kind == trigger)
            .order_by(WorldEvent.at.desc())
            .limit(limit)
        ).scalars()
    )
    return effect_over(session, events, label=trigger, horizon_hours=horizon_hours)


def effect_over(
    session: Session, events: list[WorldEvent], *, label: str, horizon_hours: int
) -> Effect | None:
    """The in-sample effect after these events — a trigger's occurrences, or
    the second events of a conjunction's pairs — labelled as the caller says.

    The unconditional column is over the same recordings **from the earliest
    occurrence on**. Before M42 it was over every bar of the recording, and
    a kind the service had only recorded for two days read as a strong
    effect against a baseline of four hundred bars because those two days
    went up. The comparison is now between the same days.
    """
    from aurelis.intel.snapshots import MarketSnapshot, Snapshots

    if not events:
        return None
    bars_by_symbol: dict[str, list[Any]] = {}
    index_by_symbol: dict[str, dict[dt.datetime, int]] = {}
    after: list[Decimal] = []
    since = min(_aware(event.at) for event in events)
    for event in events:
        symbol = event.entity_key
        if symbol not in bars_by_symbol:
            snapshot = (
                session.execute(
                    sa.select(MarketSnapshot)
                    .where(MarketSnapshot.symbol == symbol)
                    .order_by(MarketSnapshot.bars.desc(), MarketSnapshot.ref.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            bars = Snapshots.bars_of(session, snapshot.ref) if snapshot is not None else []
            bars_by_symbol[symbol] = bars
            index_by_symbol[symbol] = {b.timestamp: i for i, b in enumerate(bars)}
        bars = bars_by_symbol[symbol]
        at = _aware(event.at)
        idx = index_by_symbol[symbol].get(at)
        if idx is None:
            earlier = [i for b, i in index_by_symbol[symbol].items() if b <= at]
            idx = max(earlier) if earlier else None
        if idx is None or idx + horizon_hours >= len(bars):
            continue
        start = bars[idx].close
        end = bars[idx + horizon_hours].close
        if start > 0:
            after.append((end / start - 1) * 100)
    if not after:
        return None
    every: list[Decimal] = []
    for bars in bars_by_symbol.values():
        for i in range(len(bars) - horizon_hours):
            if _aware(bars[i].timestamp) < since:
                continue
            if bars[i].close > 0:
                every.append((bars[i + horizon_hours].close / bars[i].close - 1) * 100)
    q = Decimal("0.0001")
    return Effect(
        trigger=label,
        horizon_hours=horizon_hours,
        n=len(after),
        mean_return_after=(sum(after, Decimal(0)) / len(after)).quantize(q),
        up_rate_after=(Decimal(sum(1 for r in after if r > 0)) / len(after)).quantize(q),
        unconditional_mean_return=(sum(every, Decimal(0)) / len(every)).quantize(q)
        if every
        else Decimal(0),
        unconditional_up_rate=(
            (Decimal(sum(1 for r in every if r > 0)) / len(every)).quantize(q)
            if every
            else Decimal("0.5")
        ),
        since=since,
    )


def _aware(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
