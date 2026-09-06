"""The org-change lifecycle: propose, lock, decide, apply, measure.

Five acts, and the order is the point.

.. code-block:: text

    propose   a trigger fired; the evidence is attached
    lock      the prediction and the measurement plan are hashed
    decide    a Board meeting approves or refuses it
    apply     coverage moves; the baseline is read at that moment
    measure   the same metric, after the declared window, verdict either way

**Lock before decide.** The room never sees a prediction it can influence, and
the proposer cannot re-aim one after the outcome — a trigger freezes the
columns (ADR-0012). This is the research preregistration discipline turned on
the company itself, and it is the only reason "the split helped" can ever be
more than a recollection.

**Baseline immediately before the change, not at proposal time.** Reading it
when the proposal was written would credit the change with whatever drifted in
the days between; reading it *after* would make a structural change invisible
to itself, because both sides of the comparison would be post-change. The first
version did the latter, and a split could not be seen to have split anything.

**Measure either way.** :class:`~aurelis.orgdev.states.EffectVerdict` has
``WORSE`` and ``NO_CHANGE`` in it, and a run that produces one records it. A
company that only wrote down the org changes that worked would learn nothing
about its own judgement.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import sha256_of
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.org.charters import Seniority
from aurelis.orgdev.detection import TriggerHit
from aurelis.orgdev.handover import Handover, HandoverReport
from aurelis.orgdev.metrics import COMPANY, METRICS, read_metric
from aurelis.orgdev.states import (
    APPLICABLE_STATES,
    EffectVerdict,
    OrgChangeKind,
    OrgChangeState,
)
from aurelis.orgdev.tables import OrgChange, OrgMetricSnapshot
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["AppliedChange", "MeasuredEffect", "OrgDevelopment", "Prediction"]


@dataclass(frozen=True, slots=True)
class Prediction:
    """What the proposer says the change will do, and how it will be checked.

    ``magnitude`` is required and must be positive. "Things will get better" is
    not a prediction, because every outcome satisfies it.
    """

    metric: str
    direction: str
    magnitude: Decimal
    plan: str
    after_days: int = 7
    subject: str | None = None
    """Whose metric. Defaults to the change's subject agent; a fission that
    predicts a *company* metric names ``AURELIS`` here."""

    def __post_init__(self) -> None:
        if self.metric not in METRICS:
            raise IntegrityViolation(
                f"cannot predict {self.metric!r}: the company has no way to "
                f"compute it. Measurable metrics are {sorted(METRICS)}"
            )
        if self.direction not in {"up", "down"}:
            raise IntegrityViolation("direction must be 'up' or 'down'")
        if self.magnitude <= 0:
            raise IntegrityViolation(
                "a prediction of zero magnitude is satisfied by every outcome"
            )
        if not self.plan.strip():
            raise IntegrityViolation(
                "a prediction without a measurement plan cannot be checked"
            )

    def as_payload(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "direction": self.direction,
            "magnitude": str(self.magnitude),
            "plan": self.plan,
            "after_days": self.after_days,
            "subject": self.subject,
        }

    def digest(self) -> str:
        return sha256_of(self.as_payload())

    def describe(self) -> str:
        arrow = "up" if self.direction == "up" else "down"
        return f"{self.metric} {arrow} by at least {self.magnitude}"


@dataclass(frozen=True, slots=True)
class AppliedChange:
    """What applying a change actually did."""

    change_ref: str
    kind: OrgChangeKind
    new_agent: str | None
    report: HandoverReport | None
    baseline: Decimal | None
    baseline_detail: str

    def describe(self) -> str:
        head = f"{self.change_ref} applied"
        if self.report is not None:
            head += f": {self.report.describe()}"
        if self.baseline is None:
            return f"{head}; baseline NOT MEASURABLE — {self.baseline_detail}"
        return f"{head}; baseline {self.baseline}"


@dataclass(frozen=True, slots=True)
class MeasuredEffect:
    """What the change did, checked against what was predicted."""

    change_ref: str
    verdict: EffectVerdict
    predicted: str
    baseline: Decimal | None
    realised: Decimal | None
    detail: str

    @property
    def helped(self) -> bool:
        return self.verdict is EffectVerdict.IMPROVED

    def describe(self) -> str:
        return f"{self.change_ref}: {self.verdict.value} — {self.detail}"


class OrgDevelopment:
    """Proposes, records, applies and measures changes to the company."""

    __slots__ = ("_handover", "_ledger", "_clock")

    def __init__(
        self,
        handover: Handover | None = None,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._handover = handover or Handover(None, ledger, self._clock)
        self._ledger = ledger or Ledger(self._clock)

    # ------------------------------------------------------------- propose

    def propose(
        self,
        session: Session,
        *,
        hit: TriggerHit,
        proposed_by: str,
        prediction: Prediction,
        justification: str,
        charters: tuple[str, ...] = (),
        new_handle: str | None = None,
        counterpart: str | None = None,
        kind: OrgChangeKind | None = None,
        at: dt.datetime | None = None,
    ) -> OrgChange:
        """Write a proposal, carrying the measurement that justified it."""
        moment = at or self._clock.now()
        change_kind = kind or hit.trigger.proposes

        if proposed_by == hit.subject:
            raise IntegrityViolation(
                f"{proposed_by} may not propose a change to its own record. "
                "Self-modification would make the growth mechanism "
                "unauditable (ADR-0003)."
            )
        if change_kind is OrgChangeKind.FISSION and not charters:
            raise IntegrityViolation("a fission proposal must name the charters to split")
        if change_kind is OrgChangeKind.FISSION and not new_handle:
            raise IntegrityViolation("a fission proposal must name the new agent")
        if change_kind is OrgChangeKind.FUSION and not counterpart:
            raise IntegrityViolation("a fusion proposal must name what it merges into")

        ref = allocate_ref(session, RefKind.ORG_CHANGE)
        session.add(
            OrgChange(
                change_id=uuid7(),
                ref=ref,
                kind=change_kind.value,
                state=OrgChangeState.DRAFT,
                subject_agent=hit.subject,
                counterpart_agent=counterpart,
                charters=list(charters),
                new_handle=new_handle,
                trigger=hit.trigger.kind.value,
                trigger_evidence=hit.evidence,
                justification=justification,
                predicted_metric=prediction.metric,
                predicted_direction=prediction.direction,
                predicted_magnitude=str(prediction.magnitude),
                measurement_plan=prediction.plan,
                measure_after_days=prediction.after_days,
                proposed_by=proposed_by,
                proposed_at=moment,
            )
        )
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.ORG_CHANGE_PROPOSED,
            actor=proposed_by,
            subject=ref,
            payload={
                "kind": change_kind.value,
                "about": hit.subject,
                "trigger": hit.evidence,
                "predicts": prediction.as_payload(),
                "justification": justification,
            },
            at=moment,
        )
        return self._row(session, ref)

    def lock(
        self, session: Session, ref: str, *, at: dt.datetime | None = None
    ) -> str:
        """Hash the prediction. Nothing may change it afterwards."""
        moment = at or self._clock.now()
        change = self._row(session, ref)
        if change.state != OrgChangeState.DRAFT:
            raise IntegrityViolation(
                f"{ref} is {change.state}, not a draft; only a draft can be locked"
            )
        prediction = self._prediction_of(change)
        change.locked_digest = prediction.digest()
        change.locked_at = moment
        change.state = OrgChangeState.LOCKED
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.ORG_CHANGE_LOCKED,
            actor=Actor.SYSTEM,
            subject=ref,
            payload={
                "digest": change.locked_digest,
                "predicts": prediction.as_payload(),
                "why": (
                    "locked before the room sees it, so the prediction cannot "
                    "be re-aimed once the outcome is known"
                ),
            },
            at=moment,
        )
        return change.locked_digest

    # --------------------------------------------------------------- decide

    def decide(
        self,
        session: Session,
        ref: str,
        *,
        approved: bool,
        decided_by: str,
        meeting_ref: str,
        decision_ref: str | None = None,
        at: dt.datetime | None = None,
    ) -> OrgChange:
        """Record the room's decision."""
        moment = at or self._clock.now()
        change = self._row(session, ref)
        if change.state != OrgChangeState.LOCKED:
            raise IntegrityViolation(
                f"{ref} is {change.state}; a change must be locked before it is "
                "decided, so the room cannot influence the prediction it will "
                "later be judged against"
            )
        change.state = (
            OrgChangeState.APPROVED if approved else OrgChangeState.REJECTED
        )
        change.decided_by = decided_by
        change.meeting_ref = meeting_ref
        change.decision_ref = decision_ref
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.ORG_CHANGE_DECIDED,
            actor=decided_by,
            subject=ref,
            payload={
                "approved": approved,
                "meeting": meeting_ref,
                "decision": decision_ref,
            },
            at=moment,
        )
        return change

    # ---------------------------------------------------------------- apply

    def apply(
        self, session: Session, ref: str, *, at: dt.datetime | None = None
    ) -> AppliedChange:
        """Change the company, and read the baseline at that moment."""
        moment = at or self._clock.now()
        change = self._row(session, ref)
        if OrgChangeState(change.state) not in APPLICABLE_STATES:
            raise IntegrityViolation(
                f"{ref} is {change.state}; only an approved change may be "
                "applied. A structural edit nobody decided on is not a decision."
            )

        subject = self._prediction_of(change).subject or change.subject_agent
        new_agent: str | None = None
        report: HandoverReport | None = None
        kind = OrgChangeKind(change.kind)

        # The baseline is read here, immediately BEFORE the structure moves.
        # It was read afterwards in the first version, which made a structural
        # change invisible to itself: both sides of the comparison were
        # post-change, so a split could never be seen to have split anything.
        # Reading it at *proposal* time would be the opposite error -- it would
        # credit the change with whatever drifted in the days between.
        reading = read_metric(session, subject, change.predicted_metric, now=moment)
        change.baseline = None if reading.value is None else str(reading.value)
        session.flush()

        if kind is OrgChangeKind.FISSION:
            new_agent, report = self._handover.split(
                session,
                from_ref=change.subject_agent,
                handle=change.new_handle or "SPLIT",
                charters=tuple(change.charters),
                seniority=Seniority.SENIOR,
                change_ref=ref,
                at=moment,
            )
        elif kind is OrgChangeKind.FUSION:
            if not change.counterpart_agent:
                raise IntegrityViolation(f"{ref} is a fusion with no counterpart")
            report = self._handover.merge(
                session,
                from_ref=change.subject_agent,
                into_ref=change.counterpart_agent,
                change_ref=ref,
                at=moment,
            )

        change.applied_at = moment
        change.state = OrgChangeState.APPLIED
        session.flush()
        self._snapshot(session, subject, reading, ref, moment)

        self._ledger.append(
            session,
            kind=EventKind.ORG_CHANGE_APPLIED,
            actor=Actor.SYSTEM,
            subject=ref,
            payload={
                "kind": kind.value,
                "new_agent": new_agent,
                "handover": report.as_payload() if report else None,
                "baseline": change.baseline,
                "baseline_detail": reading.detail,
            },
            at=moment,
        )
        return AppliedChange(
            change_ref=ref,
            kind=kind,
            new_agent=new_agent,
            report=report,
            baseline=reading.value,
            baseline_detail=reading.detail,
        )

    # -------------------------------------------------------------- measure

    def measure(
        self, session: Session, ref: str, *, at: dt.datetime | None = None
    ) -> MeasuredEffect:
        """Take the predicted metric again and record what happened."""
        moment = at or self._clock.now()
        change = self._row(session, ref)
        if change.state != OrgChangeState.APPLIED:
            raise IntegrityViolation(
                f"{ref} is {change.state}; only an applied change has an effect "
                "to measure"
            )

        prediction = self._prediction_of(change)
        subject = prediction.subject or change.subject_agent
        reading = read_metric(session, subject, change.predicted_metric, now=moment)
        self._snapshot(session, subject, reading, ref, moment)

        baseline = (
            Decimal(change.baseline) if change.baseline is not None else None
        )
        verdict, detail = _judge(prediction, baseline, reading.value, reading.detail)

        change.realised = None if reading.value is None else str(reading.value)
        change.effect = verdict.value
        change.effect_detail = detail
        change.measured_at = moment
        change.state = OrgChangeState.MEASURED
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.ORG_CHANGE_MEASURED,
            actor=Actor.SYSTEM,
            subject=ref,
            payload={
                "predicted": prediction.as_payload(),
                "baseline": change.baseline,
                "realised": change.realised,
                "verdict": verdict.value,
                "detail": detail,
                "note": (
                    "recorded whichever way it came out; a company that only "
                    "kept the changes that worked would learn nothing about "
                    "its own judgement"
                ),
            },
            at=moment,
        )
        return MeasuredEffect(
            change_ref=ref,
            verdict=verdict,
            predicted=prediction.describe(),
            baseline=baseline,
            realised=reading.value,
            detail=detail,
        )

    # -------------------------------------------------------------- reading

    def get(self, session: Session, ref: str) -> OrgChange:
        return self._row(session, ref)

    def history(self, session: Session) -> list[OrgChange]:
        return list(
            session.execute(
                sa.select(OrgChange).order_by(OrgChange.proposed_at, OrgChange.ref)
            ).scalars()
        )

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _row(session: Session, ref: str) -> OrgChange:
        row = session.execute(
            sa.select(OrgChange).where(OrgChange.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no org change {ref!r}")
        return row

    @staticmethod
    def _prediction_of(change: OrgChange) -> Prediction:
        subject = (
            COMPANY
            if change.predicted_metric
            in {"agents_active", "charters_per_agent", "starved_charters"}
            else change.subject_agent
        )
        return Prediction(
            metric=change.predicted_metric,
            direction=change.predicted_direction,
            magnitude=Decimal(change.predicted_magnitude),
            plan=change.measurement_plan,
            after_days=change.measure_after_days,
            subject=subject,
        )

    @staticmethod
    def _snapshot(
        session: Session,
        subject: str,
        reading: Any,
        change_ref: str,
        moment: dt.datetime,
    ) -> None:
        session.add(
            OrgMetricSnapshot(
                snapshot_id=uuid7(),
                subject=subject,
                metric=reading.metric,
                value=None if reading.value is None else str(reading.value),
                detail=reading.detail,
                change_ref=change_ref,
                taken_at=moment,
            )
        )
        session.flush()


def _judge(
    prediction: Prediction,
    baseline: Decimal | None,
    realised: Decimal | None,
    detail: str,
) -> tuple[EffectVerdict, str]:
    """The verdict rule. Pure, so it can be argued with on its own.

    ``UNMEASURABLE`` is never a success and always names what was missing. A
    change whose metric could not be read on both sides of the window taught
    the company nothing, and recording that is more useful than recording a
    guess.
    """
    if baseline is None or realised is None:
        side = "baseline" if baseline is None else "realised value"
        return (
            EffectVerdict.UNMEASURABLE,
            f"the {side} could not be taken — {detail}",
        )

    moved = realised - baseline
    wanted = prediction.magnitude if prediction.direction == "up" else -prediction.magnitude
    right_way = moved > 0 if prediction.direction == "up" else moved < 0

    if moved == 0:
        return (
            EffectVerdict.NO_CHANGE,
            f"{prediction.metric} stayed at {baseline}; predicted {prediction.describe()}",
        )
    if not right_way:
        return (
            EffectVerdict.WORSE,
            f"{prediction.metric} moved {moved:+} — the wrong way; "
            f"predicted {prediction.describe()}",
        )
    if abs(moved) >= prediction.magnitude:
        return (
            EffectVerdict.IMPROVED,
            f"{prediction.metric} moved {moved:+} against a predicted {wanted:+}",
        )
    return (
        EffectVerdict.PARTIAL,
        f"{prediction.metric} moved {moved:+}, the right way and short of the "
        f"predicted {wanted:+}",
    )
