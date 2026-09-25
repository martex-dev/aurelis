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

from aurelis.world.tables import WorldEvent

__all__ = [
    "READINGS",
    "Effect",
    "MinedPair",
    "effect_of",
    "effect_over",
    "is_reading",
    "mine_diverse",
    "mine_pairs",
]

READINGS: frozenset[str] = frozenset(
    {
        "listing.seen",
        "book.snapshot",
        "flow.trades",
        "leverage.funding",
        "leverage.open_interest",
        "social.post",
    }
)
"""Kinds the service records as a *reading* on every wake for every followed
instrument, rather than because something happened: the catalogue sighting,
the book snapshot, the hour's trades, the funding rate and the open interest.
A reading co-occurs with everything, so a pair built on one fires on every
bar, and its in-sample "effect" is only the period the reading has been
recorded for. The first live mechanism stated on one (trades followed by an
open-interest reading, 676 predictions in a day, six right of the first
hundred and four) is why this set exists. ``social.post`` joined it at M47: the
service reads each followed instrument's stream every wake, three and a half
thousand posts in two days, and a single post is the stream, not an event;
``social.burst`` is the event. Derived kinds -- ``book.bid_heavy``,
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


_Pairs = tuple[dict[tuple[str, str], int], dict[tuple[str, str], int], dict[str, int]]
_PAIRS_CACHE: dict[tuple[Any, ...], _Pairs] = {}


def _all_pairs(
    session: Session, within: dt.timedelta
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int], dict[str, int]]:
    """Every ordered pair of kinds on the same entity inside the window, in
    one pass: ``(counts, instruments per pair, events per kind)``.

    The first version asked the database once per pair of kinds, twenty-five
    squared queries, seven and a half seconds on the live record, and the
    loop asked it every cycle. One sweep over the events, cached until the
    event stream changes, does the same count (M47).
    """
    bind = session.get_bind()
    fingerprint = session.execute(
        sa.select(sa.func.count(), sa.func.max(WorldEvent.recorded_at)).select_from(WorldEvent)
    ).one()
    key = (str(bind.engine.url), within, tuple(fingerprint))
    cached = _PAIRS_CACHE.get(key)
    if cached is not None:
        return cached
    rows = session.execute(
        sa.select(
            WorldEvent.entity_kind,
            WorldEvent.entity_key,
            WorldEvent.kind,
            WorldEvent.at,
            WorldEvent.digest,
        ).order_by(WorldEvent.entity_kind, WorldEvent.entity_key, WorldEvent.at)
    ).all()
    counts: dict[tuple[str, str], int] = {}
    entities: dict[tuple[str, str], set[str]] = {}
    per_kind: dict[str, int] = {}
    group: list[tuple[str, dt.datetime, str]] = []
    current: tuple[str, str] | None = None

    def sweep(entity: tuple[str, str], events: list[tuple[str, dt.datetime, str]]) -> None:
        n = len(events)
        start = 0
        for i in range(n):
            kind_i, at_i, digest_i = events[i]
            while start < n and events[start][1] < at_i:
                start += 1
            j = start
            limit = at_i + within
            while j < n and events[j][1] <= limit:
                if j != i and events[j][2] != digest_i:
                    pair = (kind_i, events[j][0])
                    counts[pair] = counts.get(pair, 0) + 1
                    entities.setdefault(pair, set()).add(entity[1])
                j += 1

    for ekind, ekey, kind, at, digest in rows:
        kind = str(kind)
        if is_reading(kind):
            continue
        per_kind[kind] = per_kind.get(kind, 0) + 1
        entity = (str(ekind), str(ekey))
        if entity != current:
            if current is not None:
                sweep(current, group)
            current, group = entity, []
        moment = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
        group.append((kind, moment, str(digest)))
    if current is not None:
        sweep(current, group)
    result = (counts, {p: len(e) for p, e in entities.items()}, per_kind)
    if len(_PAIRS_CACHE) > 8:
        _PAIRS_CACHE.clear()
    _PAIRS_CACHE[key] = result
    return result


def mine_pairs(
    session: Session, *, within: dt.timedelta, min_count: int = 3, limit: int = 20
) -> list[MinedPair]:
    """Every ordered pair of kinds that co-occurs at least ``min_count`` times.

    Ranked by count. A pair of the same kind (a break followed by a break) is
    a legitimate continuation pattern and is included. Readings are left out
    on both sides.
    """
    counts, instruments, _ = _all_pairs(session, within)
    out = [
        MinedPair(first, second, n, instruments[(first, second)])
        for (first, second), n in counts.items()
        if n >= min_count
    ]
    out.sort(key=lambda p: (-p.count, p.first, p.second))
    return out[:limit]


def mine_diverse(
    session: Session,
    *,
    within: dt.timedelta,
    min_count: int = 3,
    per_trigger: int = 2,
    limit: int = 24,
) -> list[MinedPair]:
    """Each trigger kind's strongest partners, the rarest triggers first.

    Ranked by count alone, the pairs the agents were shown were always the
    hourly price and flow events, which co-occur with everything because they
    happen all the time. A paid boost on a memecoin, a burst of posts, a
    headline burst never made the list. Here every trigger kind brings its
    ``per_trigger`` most frequent partners, and rarer triggers come first:
    an event that happens seldom is the one worth asking about (M47).
    """
    counts, instruments, per_kind = _all_pairs(session, within)
    by_first: dict[str, list[MinedPair]] = {}
    for (first, second), n in counts.items():
        if n >= min_count:
            by_first.setdefault(first, []).append(
                MinedPair(first, second, n, instruments[(first, second)])
            )
    chosen: list[MinedPair] = []
    for first in sorted(by_first, key=lambda k: (per_kind.get(k, 0), k)):
        ranked = sorted(by_first[first], key=lambda p: (-p.count, p.second))
        chosen.extend(ranked[:per_trigger])
    return chosen[:limit]


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
