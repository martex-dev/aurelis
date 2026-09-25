"""The market board: what each market looks like beyond its price (M49).

The first question a judge answers is which market to state a view on. Until
M49 it was shown one line per market: the close and four price changes. The
mechanisms that beat the drift key off other things -- a range break, a
bid-heavy book, one-sided taker flow -- which the service records every wake.
So the judges declined. After M48 fixed the figure guard, five of seven gave
the same reason in their own words: the mechanisms with an edge "depend on
book/flow reads I don't have here".

The board adds three things to each market's line, all read from the record
as of what the company knew at that moment (``recorded_at``, not ``at``):

* **readings** -- the newest book, flow, funding and open-interest reading, if
  it is fresh;
* **signals** -- the event kinds that fired on the instrument in the last day,
  newest first, with how long ago;
* **mechanism calls** -- the open predictions a mechanism has sealed on it,
  with the direction and when they resolve.

It is material, not advice. A mechanism's call is evidence the agent may use
or argue against; its view is still its own and is scored on its own.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.judgement.tables import Thesis
from aurelis.mechanism.mining import READINGS
from aurelis.world.tables import WorldEvent

__all__ = ["READING_FRESH", "SIGNAL_WINDOW", "BoardLine", "market_board"]

SIGNAL_WINDOW = dt.timedelta(hours=24)
"""How far back a signal is still news."""

READING_FRESH = dt.timedelta(hours=3)
"""A reading older than this is not shown: a stale book is not a book."""

MAX_SIGNALS = 5
"""The newest signal kinds per market; the rest are on the view page."""

_READING_FIELDS: dict[str, tuple[str, str]] = {
    "book.snapshot": ("bid_share", "book bid share"),
    "flow.trades": ("buy_share", "taker buy share"),
    "leverage.funding": ("annualised_pct", "funding annualised %"),
    "leverage.open_interest": ("change_24h_pct", "open interest 24h change %"),
}

_SIGNAL_DETAIL: dict[str, str] = {
    "price.range_break": "side",
    "book.bid_heavy": "bid_share",
    "flow.buy_pressure": "buy_share",
    "flow.sell_pressure": "buy_share",
    "social.burst": "mentions_6h",
    "news.burst": "mentions_6h",
    "oi.surge": "change_pct",
    "oi.purge": "change_pct",
}


@dataclass(frozen=True, slots=True)
class BoardLine:
    readings: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()

    def render(self) -> str:
        parts: list[str] = []
        if self.readings:
            parts.append("readings: " + ", ".join(self.readings))
        if self.signals:
            parts.append("fired lately: " + ", ".join(self.signals))
        if self.calls:
            parts.append("open mechanism calls: " + ", ".join(self.calls))
        return "; ".join(parts)

    def as_material(self) -> dict[str, Any]:
        return {
            "readings": list(self.readings) or ["none fresh"],
            "fired in the last day": list(self.signals) or ["nothing"],
            "open mechanism calls": list(self.calls) or ["none"],
        }


def _aware(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def _hours_ago(moment: dt.datetime, then: dt.datetime) -> str:
    hours = int((moment - _aware(then)).total_seconds() // 3600)
    return "this hour" if hours < 1 else f"{hours}h ago"


def market_board(
    session: Session, symbols: tuple[str, ...] | list[str], moment: dt.datetime
) -> dict[str, BoardLine]:
    """Each market's readings, recent signals and open mechanism calls."""
    wanted = list(dict.fromkeys(symbols))
    if not wanted:
        return {}
    moment = _aware(moment)
    rows = session.execute(
        sa.select(WorldEvent.entity_key, WorldEvent.kind, WorldEvent.at, WorldEvent.payload)
        .where(
            WorldEvent.entity_kind == "instrument",
            WorldEvent.entity_key.in_(wanted),
            WorldEvent.at >= moment - SIGNAL_WINDOW,
            WorldEvent.recorded_at <= moment,
            WorldEvent.kind != "social.post",
        )
        .order_by(WorldEvent.at.desc())
    ).all()
    readings: dict[str, dict[str, str]] = {}
    signals: dict[str, dict[str, str]] = {}
    for key, kind, at, payload in rows:
        if kind in _READING_FIELDS:
            field, label = _READING_FIELDS[kind]
            value = (payload or {}).get(field)
            if value in (None, "") or moment - _aware(at) > READING_FRESH:
                continue
            readings.setdefault(key, {}).setdefault(label, f"{label} {value}")
        elif kind not in READINGS:
            seen = signals.setdefault(key, {})
            if kind in seen or len(seen) >= MAX_SIGNALS:
                continue
            detail_field = _SIGNAL_DETAIL.get(kind)
            detail = (payload or {}).get(detail_field) if detail_field else None
            name = kind if detail in (None, "") else f"{kind} ({detail_field} {detail})"
            seen[kind] = f"{name} {_hours_ago(moment, at)}"

    calls: dict[str, list[str]] = {}
    open_calls = session.execute(
        sa.select(Thesis.instrument, Thesis.mechanism_ref, Thesis.direction, Thesis.resolves_at)
        .where(
            Thesis.mechanism_ref.is_not(None),
            Thesis.outcome.is_(None),
            Thesis.instrument.in_(wanted),
            Thesis.resolves_at > moment,
            Thesis.sealed_at <= moment,
        )
        .order_by(Thesis.resolves_at)
    ).all()
    for instrument, mechanism, direction, resolves in open_calls:
        line = f"{mechanism} says {direction} by {_aware(resolves):%Y-%m-%d %H:%M}Z"
        mine = calls.setdefault(instrument, [])
        if not any(c.startswith(f"{mechanism} ") for c in mine):
            mine.append(line)

    return {
        symbol: BoardLine(
            tuple(readings.get(symbol, {}).values()),
            tuple(signals.get(symbol, {}).values()),
            tuple(calls.get(symbol, [])),
        )
        for symbol in wanted
    }
