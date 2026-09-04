"""Point-in-time universe resolution.

Survivorship bias is not a subtle statistical artefact. It is the difference
between two lists:

* **hindsight** — the instruments that are still trading *today*;
* **point-in-time** — the instruments a person could actually have chosen on
  the start date, including the ones that later died.

A backtest run over the first list has quietly been told which names survive.
It cannot lose money on a delisting, because the delisted names were never in
it. That is not a small correction: in martex-quant's own corpus it was the
single defect that turned a headline result into a dead one, and it is the
reason ``point_in_time`` is a first-class field on the specification rather
than a footnote in a data pipeline.

The two lists are produced here, from the same source, so the difference
between them is a measurement rather than an argument. That is what lets a
Critic raise SURVIVORSHIP and have the Chair *settle* it inside a meeting.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

__all__ = ["ResolvedUniverse", "resolve_universe"]


@dataclass(frozen=True, slots=True)
class ResolvedUniverse:
    """The instruments a specification actually gets to trade."""

    symbols: tuple[str, ...]
    point_in_time: bool
    as_of: dt.datetime
    excluded: tuple[str, ...]
    """Names the hindsight list dropped. Empty when point-in-time.

    Reported rather than discarded: "which names did selecting for survivors
    remove?" is the question a Data Auditor asks, and it must be answerable
    from the run itself.
    """

    @property
    def survivorship_exposed(self) -> bool:
        """True when this universe was chosen with hindsight and it mattered."""
        return not self.point_in_time and bool(self.excluded)

    def describe(self) -> str:
        basis = "point-in-time" if self.point_in_time else "hindsight (survivors only)"
        note = f"; excluded {', '.join(self.excluded)}" if self.excluded else ""
        return f"{len(self.symbols)} symbols, {basis}{note}"


def resolve_universe(
    desk: str,
    requested: tuple[str, ...],
    *,
    point_in_time: bool,
    as_of: dt.datetime,
) -> ResolvedUniverse:
    """Which instruments this run may trade, and on what basis.

    ``point_in_time=True`` returns everything listed as of ``as_of``, including
    names that later delisted. ``False`` returns only what is still trading —
    the hindsight list, which is what a careless universe definition produces
    and what SURVIVORSHIP objects to.

    An explicit symbol list is honoured as given: a caller that named its
    instruments has already made the selection, and quietly widening it would
    be answering a different question than the one the spec asked.
    """
    from aurelis.intel.sources import source_for

    source = source_for(desk)
    listed = source.listed_as_of(as_of)
    surviving = source.surviving()

    if requested:
        chosen = tuple(s for s in requested if s in listed) if point_in_time else tuple(
            s for s in requested if s in surviving
        )
        excluded = () if point_in_time else tuple(s for s in requested if s not in surviving)
        return ResolvedUniverse(chosen, point_in_time, as_of, excluded)

    if point_in_time:
        return ResolvedUniverse(listed, True, as_of, ())
    return ResolvedUniverse(
        surviving, False, as_of, tuple(s for s in listed if s not in surviving)
    )
