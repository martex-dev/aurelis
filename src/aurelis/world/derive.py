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

from sqlalchemy.orm import Session

from aurelis.intel.snapshots import MarketSnapshot, Snapshots
from aurelis.world.store import World

__all__ = ["SPIKE", "WINDOW", "derive_price_events"]

WINDOW = 168
SPIKE = Decimal("3")


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
