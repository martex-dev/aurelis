"""Applying a mechanism to every occurrence, as a sealed forward prediction.

A mechanism states: *when the trigger fires, the instrument moves this way over
this horizon, at this confidence.* This module turns that into predictions —
one per occurrence of the trigger event that the mechanism has not already
predicted — and seals each as a thesis before its outcome exists, tagged with
the mechanism. Scoring then flows through exactly the M25 resolver, and the
mechanism's calibration is read from its tagged theses.

A prediction is mechanical: there is no model call. The mechanism was authored
once, with reasoning; each prediction is that reasoning applied. What makes it
evidence is that it is sealed before the outcome and scored against a recording
— the same forward discipline a judgement gets, on a rule instead of a view.

Three rules hold it honest:

* **The reference close is what was knowable at the trigger.** The prediction
  is made against the close of the bar the trigger event fired on, from a
  recording that covers it — never a later price.
* **A prediction whose horizon has already passed is not sealed.** The trigger
  event may be old; a prediction on it would be settled the moment it was made,
  which is not a prediction. It is skipped, not sealed as free money.
* **One prediction per occurrence.** The trigger event's own digest keys the
  thesis, so re-running generation seals nothing new.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import sha256_of
from aurelis.core.clock import Clock, SystemClock, isoformat
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.snapshots import MarketSnapshot, SnapshotBar
from aurelis.judgement.seat import seal_of
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.tables import Mechanism
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger
from aurelis.world.tables import WorldEvent

__all__ = ["PredictionRun", "generate_predictions"]


@dataclass(frozen=True, slots=True)
class PredictionRun:
    """What one generation pass sealed."""

    mechanism_ref: str
    sealed: tuple[str, ...]
    skipped_past: int
    skipped_no_recording: int
    already: int

    def describe(self) -> str:
        return (
            f"{self.mechanism_ref}: sealed {len(self.sealed)}, "
            f"{self.already} already predicted, {self.skipped_past} whose horizon "
            f"had passed, {self.skipped_no_recording} with no covering recording"
        )


def _covering_close(
    session: Session, *, instrument: str, at: dt.datetime
) -> tuple[MarketSnapshot, dt.datetime, Decimal] | None:
    """The close of the bar that opened at or before ``at``, from a recording
    that covers it. What was knowable at the trigger, and nothing later."""
    snapshot = (
        session.execute(
            sa.select(MarketSnapshot)
            .where(
                MarketSnapshot.symbol == instrument,
                MarketSnapshot.first_at <= at,
                MarketSnapshot.last_at >= at,
            )
            .order_by(MarketSnapshot.fetched_at.desc(), MarketSnapshot.ref.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if snapshot is None:
        return None
    bar = session.execute(
        sa.select(SnapshotBar.timestamp, SnapshotBar.close)
        .where(SnapshotBar.snapshot_ref == snapshot.ref, SnapshotBar.timestamp <= at)
        .order_by(SnapshotBar.timestamp.desc())
        .limit(1)
    ).first()
    if bar is None:
        return None
    when = bar[0] if bar[0].tzinfo else bar[0].replace(tzinfo=dt.UTC)
    return snapshot, when, Decimal(str(bar[1]))


def _occurrences(session: Session, mechanism: Mechanism) -> list[WorldEvent]:
    """What fires the mechanism, oldest first.

    On the trigger alone: every event of the trigger kind. On a conjunction:
    every event of the second kind that follows a trigger within the window on
    the same instrument — the instant the conjunction completes, which is the
    first moment anyone could have acted on it. A second event that completes
    several pairs (two triggers, then one follow) is one occurrence: the
    conjunction happened once.
    """
    if not mechanism.then_kind:
        return list(
            session.execute(
                sa.select(WorldEvent)
                .where(WorldEvent.kind == mechanism.trigger_kind)
                .order_by(WorldEvent.at)
            ).scalars()
        )
    from aurelis.world.store import World

    pairs = World.co_occurrences(
        session,
        first_kind=mechanism.trigger_kind,
        second_kind=mechanism.then_kind,
        within=dt.timedelta(hours=int(mechanism.within_hours or 0)),
        limit=100_000,
    )
    seen: set[str] = set()
    seconds: list[WorldEvent] = []
    for pair in pairs:
        if pair.second.digest in seen:
            continue
        seen.add(pair.second.digest)
        seconds.append(pair.second)
    seconds.sort(key=lambda event: (event.at, event.digest))
    return seconds


def generate_predictions(
    session: Session,
    mechanism: Mechanism,
    *,
    ledger: Ledger | None = None,
    clock: Clock | None = None,
    at: dt.datetime | None = None,
    limit: int = 200,
) -> PredictionRun:
    """Seal a prediction for every occurrence of the mechanism's trigger.

    Occurrences are world events of the trigger kind. The first one the
    mechanism was found on is sealed too, marked as training, so the record
    shows the instance it was fitted on apart from the ones that test it.
    """
    the_clock = clock or SystemClock()
    the_ledger = ledger or Ledger(the_clock)
    moment = at or the_clock.now()
    confidence = Decimal(str(mechanism.confidence))
    probability_up = confidence if mechanism.direction == "up" else Decimal(1) - confidence

    occurrences = _occurrences(session, mechanism)
    sealed: list[str] = []
    skipped_past = 0
    skipped_no_recording = 0
    already = 0

    for occurrence in occurrences:
        pkey = sha256_of({"mechanism": mechanism.ref, "trigger": occurrence.digest})
        existing = session.execute(
            sa.select(Thesis.ref).where(Thesis.mechanism_prediction_key == pkey)
        ).first()
        if existing is not None:
            already += 1
            continue

        trigger_at = occurrence.at if occurrence.at.tzinfo else occurrence.at.replace(tzinfo=dt.UTC)
        resolves_at = trigger_at + dt.timedelta(hours=mechanism.horizon_hours)
        # Forward only. A mechanism stated now cannot predict an occurrence
        # whose horizon already elapsed -- that outcome exists, and sealing it
        # would be recording a backward "prediction". Those occurrences are
        # what the mechanism was mined on; the ones it is tested on arrive
        # after it is stated, as the service keeps recording.
        if resolves_at <= moment:
            skipped_past += 1
            continue
        covering = _covering_close(session, instrument=occurrence.entity_key, at=trigger_at)
        if covering is None:
            skipped_no_recording += 1
            continue
        snapshot, reference_at, reference_close = covering
        if resolves_at <= reference_at:  # pragma: no cover - implied by resolves_at > moment
            skipped_past += 1
            continue

        is_training = (
            occurrence.entity_key == mechanism.found_on_instrument
            and mechanism.found_on_event in (occurrence.digest, occurrence.digest[:16])
        )
        ref = allocate_ref(session, RefKind.THESIS)
        text = (
            f"Mechanism {mechanism.ref} ({mechanism.title}): when "
            f"{mechanism.fires_on} fires, {occurrence.entity_key} moves "
            f"{mechanism.direction} over {mechanism.horizon_hours} bars. This is "
            f"occurrence at {isoformat(trigger_at)}, close {reference_close}."
        )
        row = Thesis(
            thesis_id=uuid7(),
            ref=ref,
            agent_ref=mechanism.agent_ref,
            desk=mechanism.desk,
            instrument=occurrence.entity_key,
            interval=snapshot.interval,
            horizon_hours=mechanism.horizon_hours,
            snapshot_ref=snapshot.ref,
            reference_at=reference_at,
            reference_close=str(reference_close),
            resolves_at=resolves_at,
            is_live=bool(snapshot.is_live),
            direction=mechanism.direction,
            confidence=confidence,
            probability_up=probability_up,
            thesis=text,
            wrong_if=(
                f"the close {mechanism.horizon_hours} bars after the trigger is on "
                f"the other side of {reference_close}"
            ),
            material_digest=occurrence.digest,
            model=f"mechanism:{mechanism.ref}",
            mechanism_ref=mechanism.ref,
            mechanism_training=is_training,
            mechanism_prediction_key=pkey,
            sealed_at=moment,
            seal="0" * 64,
        )
        row.seal = seal_of(row)
        session.add(row)
        session.flush()
        sealed.append(ref)
        if len(sealed) >= limit:
            break

    if sealed:
        the_ledger.append(
            session,
            kind=EventKind.MECHANISM_PREDICTED,
            actor=Actor.SYSTEM,
            subject=mechanism.ref,
            payload={"sealed": len(sealed), "trigger": mechanism.fires_on},
            at=moment,
        )
    return PredictionRun(
        mechanism_ref=mechanism.ref,
        sealed=tuple(sealed),
        skipped_past=skipped_past,
        skipped_no_recording=skipped_no_recording,
        already=already,
    )


def generate_all(
    session: Session,
    mechanisms: Any,
    *,
    ledger: Ledger | None = None,
    clock: Clock | None = None,
    at: dt.datetime | None = None,
) -> list[PredictionRun]:
    """Generate predictions for every active mechanism."""
    return [
        generate_predictions(session, row, ledger=ledger, clock=clock, at=at)
        for row in mechanisms.active(session)
    ]
