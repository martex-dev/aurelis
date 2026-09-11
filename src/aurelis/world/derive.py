"""Events derived from a recording, deterministically.

Price is one event type among many, and only its notable moments enter the
stream. Two are derived here, from a snapshot's own bars, with the snapshot
as the source so the provenance is a hash:

``price.volume_spike``
    A bar whose volume is at least ``SPIKE`` times the median of the
    preceding ``WINDOW`` bars.

``price.range_break``
    A bar whose close is above the highest close, or below the lowest, of the
    preceding ``WINDOW`` bars.

Both are functions of the bars up to and including the bar they mark; the
window is the same 168 hours the judges are shown. Derivation is idempotent:
the event digest is over the bar and its payload, so deriving twice from the
same recording, or from a later recording that covers the same bar, records
nothing new.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from aurelis.intel.snapshots import MarketSnapshot, Snapshots
from aurelis.world.store import World

__all__ = ["DRAWDOWN", "SPIKE", "SQUEEZE", "WINDOW", "derive_price_events"]

WINDOW = 168
SPIKE = Decimal("3")
SQUEEZE = Decimal("0.5")
"""``price.volatility_squeeze``: the last 24 bars' range is under half the
median 24-bar range of the window; ``price.volatility_expansion`` is over
twice it."""

DRAWDOWN = Decimal("0.10")
"""``price.drawdown``: a close at least ten percent below the window high,
recorded once per entry below the line."""


def derive_price_events(
    session: Session,
    world: World,
    snapshot: MarketSnapshot,
    *,
    at: dt.datetime | None = None,
    tail: int = 400,
) -> int:
    """Derive notable-price events from the last ``tail`` bars of a recording.

    Returns how many events were new. The instrument entity is seen as a side
    effect, so a recording of a market the catalogue has not been synced for
    still has somewhere to hang its events.
    """
    bars = Snapshots.bars_of(session, snapshot.ref)
    if len(bars) <= WINDOW:
        return 0
    fetched = snapshot.fetched_at
    # The snapshot column is a plain timezone-aware DateTime, which SQLite
    # hands back naive. Everything downstream refuses naive, correctly.
    moment = at or (fetched if fetched.tzinfo else fetched.replace(tzinfo=dt.UTC))
    world.see(
        session,
        kind="instrument",
        key=snapshot.symbol,
        source=f"{snapshot.source}:{snapshot.ref}",
        at=moment,
    )
    source = f"derived:{snapshot.ref}"
    start = max(WINDOW, len(bars) - tail)
    new = 0
    for index in range(start, len(bars)):
        window = bars[index - WINDOW : index]
        bar = bars[index]
        volumes = [b.volume for b in window if b.volume > 0]
        if volumes:
            typical = Decimal(median(volumes))
            if typical > 0 and bar.volume >= SPIKE * typical:
                _, created = world.record(
                    session,
                    kind="price.volume_spike",
                    at=bar.timestamp,
                    entity_kind="instrument",
                    entity_key=snapshot.symbol,
                    payload={
                        "volume": str(bar.volume),
                        "median_volume": str(typical.quantize(Decimal("0.01"))),
                        "multiple": str((bar.volume / typical).quantize(Decimal("0.1"))),
                        "close": str(bar.close),
                    },
                    source=source,
                    recorded_at=moment,
                )
                new += int(created)
        highest = max(b.close for b in window)
        lowest = min(b.close for b in window)
        new += _derive_regime(session, world, snapshot, bars, index, window, source, moment)
        if bar.close > highest or bar.close < lowest:
            _, created = world.record(
                session,
                kind="price.range_break",
                at=bar.timestamp,
                entity_kind="instrument",
                entity_key=snapshot.symbol,
                payload={
                    "side": "above" if bar.close > highest else "below",
                    "close": str(bar.close),
                    "prior_high": str(highest),
                    "prior_low": str(lowest),
                    "window_bars": WINDOW,
                },
                source=source,
                recorded_at=moment,
            )
            new += int(created)
    return new


def _range(bars: list[Any]) -> Decimal:
    return Decimal(max(b.high for b in bars)) - Decimal(min(b.low for b in bars))


def _derive_regime(
    session: Session,
    world: World,
    snapshot: MarketSnapshot,
    bars: list[Any],
    index: int,
    window: list[Any],
    source: str,
    moment: dt.datetime,
) -> int:
    """Momentum flips, volatility squeezes and expansions, drawdowns.

    Each is a function of the bars up to and including ``index``, recorded once
    per entry into the state rather than on every bar inside it, so a week in
    a squeeze is one event and not a hundred and sixty-eight.
    """
    if index < 48:
        return 0
    bar = bars[index]
    new = 0

    # Momentum flip: the 24-bar return changes sign against the prior bar.
    ret_now = bar.close - bars[index - 24].close
    ret_prev = bars[index - 1].close - bars[index - 25].close
    if (ret_now > 0) != (ret_prev > 0) and ret_now != 0 and ret_prev != 0:
        _, created = world.record(
            session,
            kind="price.momentum_flip",
            at=bar.timestamp,
            entity_kind="instrument",
            entity_key=snapshot.symbol,
            payload={
                "to": "up" if ret_now > 0 else "down",
                "close": str(bar.close),
                "return_24": str(ret_now.quantize(Decimal("0.01"))),
            },
            source=source,
            recorded_at=moment,
        )
        new += int(created)

    # Volatility: the last 24 bars' range against the window's median 24-bar range.
    recent = _range(bars[index - 23 : index + 1])
    typical_ranges = [_range(window[i : i + 24]) for i in range(0, len(window) - 24, 24)]
    if typical_ranges:
        typical = Decimal(median(typical_ranges))
        prior = _range(bars[index - 24 : index])
        if typical > 0:
            squeezed_now = recent < SQUEEZE * typical
            squeezed_before = prior < SQUEEZE * typical
            expanded_now = recent > 2 * typical
            expanded_before = prior > 2 * typical
            if squeezed_now and not squeezed_before:
                _, created = world.record(
                    session,
                    kind="price.volatility_squeeze",
                    at=bar.timestamp,
                    entity_kind="instrument",
                    entity_key=snapshot.symbol,
                    payload={
                        "range_24": str(recent.quantize(Decimal("0.01"))),
                        "typical_range_24": str(typical.quantize(Decimal("0.01"))),
                        "close": str(bar.close),
                    },
                    source=source,
                    recorded_at=moment,
                )
                new += int(created)
            if expanded_now and not expanded_before:
                _, created = world.record(
                    session,
                    kind="price.volatility_expansion",
                    at=bar.timestamp,
                    entity_kind="instrument",
                    entity_key=snapshot.symbol,
                    payload={
                        "range_24": str(recent.quantize(Decimal("0.01"))),
                        "typical_range_24": str(typical.quantize(Decimal("0.01"))),
                        "close": str(bar.close),
                    },
                    source=source,
                    recorded_at=moment,
                )
                new += int(created)

    # Drawdown: entering the zone at least DRAWDOWN below the window high.
    high = max(b.close for b in window)
    if high > 0:
        below_now = bar.close <= high * (1 - DRAWDOWN)
        prior_high = (
            max(b.close for b in bars[index - WINDOW - 1 : index - 1]) if index > WINDOW else high
        )
        below_before = bars[index - 1].close <= prior_high * (1 - DRAWDOWN)
        if below_now and not below_before:
            _, created = world.record(
                session,
                kind="price.drawdown",
                at=bar.timestamp,
                entity_kind="instrument",
                entity_key=snapshot.symbol,
                payload={
                    "close": str(bar.close),
                    "window_high": str(high),
                    "drawdown": str(((1 - bar.close / high) * 100).quantize(Decimal("0.1"))) + "%",
                },
                source=source,
                recorded_at=moment,
            )
            new += int(created)
    return new
