"""One burst rule for every attention stream.

A burst is when an entity's events of one kind over the last six hours are
both several and several times its trailing week's six-hour rate. The rule
is the same for headlines and for social posts; the kinds differ. The
threshold travels in the event so a reader of the record knows what was
asked of the count, and the same burst is derived once per wake at most,
because the event's instant is the wake's. A rate needs history: with no
event older than six hours the trailing rate is unknown, and nothing is a
burst against an unknown rate.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aurelis.world.store import World

__all__ = ["BURST_FACTOR", "BURST_MIN", "derive_burst"]

BURST_MIN = 3
"""Fewer events than this in six hours is never a burst, whatever the rate."""

BURST_FACTOR = Decimal("3")
"""Events in the last six hours at or past this multiple of the trailing
week's six-hour rate is a burst."""

_WINDOW = dt.timedelta(hours=6)
_BASELINE = dt.timedelta(days=7)


def derive_burst(
    session: Session,
    world: World,
    *,
    entity_kind: str,
    entity_key: str,
    kind_in: str,
    kind_out: str,
    source: str,
    moment: dt.datetime,
    minimum: int = BURST_MIN,
    factor: Decimal = BURST_FACTOR,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Record ``kind_out`` on the entity if its ``kind_in`` events burst. Returns
    whether a new event was written."""
    recent = World.events_for(
        session,
        entity_kind=entity_kind,
        entity_key=entity_key,
        since=moment - _BASELINE,
        kinds=(kind_in,),
        limit=5000,
    )
    last_six = [e for e in recent if _aware(e.at) > moment - _WINDOW]
    earlier = [e for e in recent if _aware(e.at) <= moment - _WINDOW]
    if not earlier:
        # No event older than six hours: the trailing rate is unknown, not
        # zero. The first reading of a stream is not a burst on every
        # instrument it names; the second wake has a rate to compare with.
        return False
    baseline_hours = Decimal((_BASELINE - _WINDOW).total_seconds()) / Decimal(3600)
    baseline_six = (Decimal(len(earlier)) / baseline_hours * Decimal(6)).quantize(Decimal("0.01"))
    count = len(last_six)
    if count < minimum or Decimal(count) < factor * max(baseline_six, Decimal("0.5")):
        return False
    payload: dict[str, Any] = {
        "mentions_6h": count,
        "baseline_6h": str(baseline_six),
        "threshold": f">= {minimum} and >= {factor}x the trailing week's 6h rate",
    }
    if extra:
        payload.update(extra)
    _, created = world.record(
        session,
        kind=kind_out,
        at=moment,
        entity_kind=entity_kind,
        entity_key=entity_key,
        payload=payload,
        source=source,
        recorded_at=moment,
    )
    return created


def _aware(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
