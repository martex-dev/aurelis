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

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.world.store import World
from aurelis.world.tables import WorldEvent

__all__ = ["MinedPair", "mine_pairs"]

_NOT_A_TRIGGER: frozenset[str] = frozenset({"listing.seen"})
"""Kinds that are facts about the company seeing the catalogue rather than
about a market moving. A first-sync sighting of 837 products is not a
trigger anything should fire on."""


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
        if str(k) not in _NOT_A_TRIGGER
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
