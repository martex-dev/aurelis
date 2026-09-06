"""Risk, as an authority rather than a reviewer.

The design rule from `CLAUDE.md` §12 is that Risk must be able to reject,
shrink, limit, suspend and halt — and that its decisions are recorded. The
implementation rule that makes that real is narrower and harder: **nothing can
reach execution without passing through here**, and that is enforced by the
database rather than by everyone remembering.

So :func:`approve` does not take an exposure. It takes a proposal and looks up
that proposal's assessment, and a trigger refuses an approval whose assessment
belongs to a different proposal. There is no argument an eager caller can pass
to skip the step.

Every assessment is written, including ``ALLOW``. An organisation that only
recorded interventions could not distinguish a trade Risk examined and
permitted from one Risk never saw, and those are the two cases an auditor most
needs to tell apart.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger
from aurelis.risk.tables import (
    KillLatch,
    RiskAssessment,
    RiskLimit,
    TradeApproval,
    TradeProposal,
)
from aurelis.strategy.states import RiskDecision

__all__ = ["AppliedLimit", "Risk"]


@dataclass(frozen=True, slots=True)
class AppliedLimit:
    """One bound that bit, and by how much."""

    scope: str
    scope_id: str
    metric: str
    bound: Decimal
    reason: str

    def as_payload(self) -> dict[str, str]:
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "metric": self.metric,
            "bound": str(self.bound),
            "reason": self.reason,
        }


class Risk:
    """The independent authority. Writes assessments; nothing else may."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # ------------------------------------------------------------- limits

    def set_limit(
        self,
        session: Session,
        *,
        scope: str,
        scope_id: str,
        metric: str,
        bound: Decimal,
        reason: str,
        set_by: str,
        at: dt.datetime | None = None,
    ) -> RiskLimit:
        """Impose a bound. Never deleted — lifted, with a reason."""
        if not reason.strip():
            raise IntegrityViolation(
                "a limit must say why it exists; an unexplained bound cannot be "
                "argued with and will outlive the condition that caused it"
            )
        moment = at or self._clock.now()
        limit = RiskLimit(
            limit_id=uuid7(),
            scope=scope,
            scope_id=scope_id,
            metric=metric,
            bound=bound,
            reason=reason,
            set_by=set_by,
            set_at=moment,
        )
        session.add(limit)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.RISK_LIMIT_SET,
            actor=set_by,
            subject=f"{scope}:{scope_id}",
            payload={"metric": metric, "bound": str(bound), "reason": reason},
            at=moment,
        )
        return limit

    def live_limits(
        self, session: Session, *, scopes: dict[str, str], metric: str
    ) -> list[RiskLimit]:
        """Every unlifted limit on ``metric`` that covers any of these scopes."""
        if not scopes:
            return []
        clauses = [
            sa.and_(RiskLimit.scope == scope, RiskLimit.scope_id == scope_id)
            for scope, scope_id in scopes.items()
        ]
        return list(
            session.execute(
                sa.select(RiskLimit)
                .where(
                    RiskLimit.metric == metric,
                    RiskLimit.lifted_at.is_(None),
                    sa.or_(*clauses),
                )
                .order_by(RiskLimit.bound)
            ).scalars()
        )

    # --------------------------------------------------------- assessment

    def assess(
        self,
        session: Session,
        *,
        proposal_ref: str,
        assessor: str,
        at: dt.datetime | None = None,
    ) -> RiskAssessment:
        """Decide what this proposal is allowed to do.

        Mechanical: the tightest live limit wins, a latched kill halts
        everything, and the decision follows from the numbers rather than from
        an opinion. An assessment is written in every case — ``ALLOW`` included
        — because "Risk permitted this" is a fact worth having on the record.
        """
        moment = at or self._clock.now()
        proposal = self._proposal(session, proposal_ref)

        existing = session.execute(
            sa.select(RiskAssessment).where(
                RiskAssessment.proposal_ref == proposal_ref
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        scopes = {
            "company": "AURELIS",
            "desk": proposal.desk,
            "version": proposal.version_ref,
        }
        latch = self._active_latch(session, scopes)
        if latch is not None:
            return self._write(
                session,
                proposal=proposal,
                assessor=assessor,
                allowed=Decimal("0"),
                decision=RiskDecision.HALT,
                limits=[],
                reason=(
                    f"execution is halted: {latch.tripwire} latched at "
                    f"{latch.latched_at.isoformat()} ({latch.detail}). A latch "
                    "is never cleared by code"
                ),
                at=moment,
            )

        limits = self.live_limits(session, scopes=scopes, metric="exposure")
        applied = [
            AppliedLimit(
                limit.scope, limit.scope_id, limit.metric, limit.bound, limit.reason
            )
            for limit in limits
        ]
        desired = proposal.desired_exposure
        allowed = desired
        for limit in limits:
            allowed = min(allowed, limit.bound)

        if allowed <= 0:
            decision = RiskDecision.VETO
            allowed = Decimal("0")
            reason = (
                "every permitted size is zero under the live limits: "
                + "; ".join(f"{a.scope}:{a.metric} <= {a.bound}" for a in applied)
            )
        elif allowed < desired:
            decision = RiskDecision.SHRINK
            reason = (
                f"desired {desired} exceeds the tightest live limit {allowed} "
                + "; ".join(f"({a.scope} {a.reason})" for a in applied)
            )
        else:
            decision = RiskDecision.ALLOW
            reason = (
                "no live limit binds this proposal; recorded so that permitted "
                "and unexamined are different rows"
            )

        return self._write(
            session,
            proposal=proposal,
            assessor=assessor,
            allowed=allowed,
            decision=decision,
            limits=applied,
            reason=reason,
            at=moment,
        )

    def _write(
        self,
        session: Session,
        *,
        proposal: TradeProposal,
        assessor: str,
        allowed: Decimal,
        decision: RiskDecision,
        limits: list[AppliedLimit],
        reason: str,
        at: dt.datetime,
    ) -> RiskAssessment:
        ref = allocate_ref(session, RefKind.RISK_ASSESSMENT)
        assessment = RiskAssessment(
            assessment_id=uuid7(),
            ref=ref,
            proposal_ref=proposal.ref,
            assessor=assessor,
            desired_exposure=proposal.desired_exposure,
            allowed_exposure=allowed,
            decision=decision.value,
            limits_applied=[limit.as_payload() for limit in limits],
            reason=reason,
            assessed_at=at,
        )
        session.add(assessment)
        proposal.allowed_exposure = allowed
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.RISK_ASSESSED,
            actor=assessor,
            subject=proposal.ref,
            payload={
                "assessment": ref,
                "decision": decision.value,
                "desired": str(proposal.desired_exposure),
                "allowed": str(allowed),
                "limits": len(limits),
            },
            at=at,
        )
        return assessment

    # ---------------------------------------------------------- approval

    def approve(
        self,
        session: Session,
        *,
        proposal_ref: str,
        approver: str,
        at: dt.datetime | None = None,
    ) -> TradeApproval:
        """Approve a proposal at the size Risk permitted, and no larger.

        Takes no exposure argument. The final target is read from the
        assessment, so there is no parameter through which an eager caller
        could approve more than Risk allowed.
        """
        moment = at or self._clock.now()
        proposal = self._proposal(session, proposal_ref)
        assessment = session.execute(
            sa.select(RiskAssessment).where(
                RiskAssessment.proposal_ref == proposal_ref
            )
        ).scalar_one_or_none()

        if assessment is None:
            raise IntegrityViolation(
                f"{proposal_ref} has no risk assessment. A proposal Risk has "
                "not seen cannot be approved — and the database refuses it too, "
                "so this check is a clearer error rather than the only defence"
            )
        if assessment.decision in (RiskDecision.VETO.value, RiskDecision.HALT.value):
            self._ledger.append(
                session,
                kind=EventKind.TRADE_REFUSED,
                actor=approver,
                subject=proposal_ref,
                payload={
                    "decision": assessment.decision,
                    "reason": assessment.reason,
                },
                at=moment,
            )
            raise IntegrityViolation(
                f"{proposal_ref} was {assessment.decision} by Risk: "
                f"{assessment.reason}"
            )

        ref = allocate_ref(session, RefKind.TRADE_APPROVAL)
        approval = TradeApproval(
            approval_id=uuid7(),
            ref=ref,
            proposal_ref=proposal_ref,
            assessment_ref=assessment.ref,
            final_target=assessment.allowed_exposure,
            approved_by=approver,
            approved_at=moment,
        )
        session.add(approval)
        proposal.final_target = assessment.allowed_exposure
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.TRADE_APPROVED,
            actor=approver,
            subject=proposal_ref,
            payload={
                "approval": ref,
                "assessment": assessment.ref,
                "desired": str(proposal.desired_exposure),
                "final": str(assessment.allowed_exposure),
            },
            at=moment,
        )
        return approval

    # -------------------------------------------------------------- kill

    def latch(
        self,
        session: Session,
        *,
        scope: str,
        scope_id: str,
        tripwire: str,
        observed: str,
        threshold: str,
        detail: str,
        at: dt.datetime | None = None,
    ) -> KillLatch:
        """Trip a preregistered kill switch. There is no matching clear().

        Deliberately one-way. A latch a program can release is a pause, and the
        point of a latch is that somebody has to understand what died first.
        """
        moment = at or self._clock.now()
        latch = KillLatch(
            latch_id=uuid7(),
            scope=scope,
            scope_id=scope_id,
            tripwire=tripwire,
            observed=observed,
            threshold=threshold,
            detail=detail,
            latched_at=moment,
        )
        session.add(latch)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.KILL_LATCHED,
            actor="risk",
            subject=f"{scope}:{scope_id}",
            payload={
                "tripwire": tripwire,
                "observed": observed,
                "threshold": threshold,
                "detail": detail,
            },
            at=moment,
        )
        return latch

    def _active_latch(
        self, session: Session, scopes: dict[str, str]
    ) -> KillLatch | None:
        clauses = [
            sa.and_(KillLatch.scope == scope, KillLatch.scope_id == scope_id)
            for scope, scope_id in scopes.items()
        ]
        return session.execute(
            sa.select(KillLatch)
            .where(KillLatch.cleared_at.is_(None), sa.or_(*clauses))
            .order_by(KillLatch.latched_at)
        ).scalars().first()

    # ----------------------------------------------------------- reading

    @staticmethod
    def _proposal(session: Session, ref: str) -> TradeProposal:
        row = session.execute(
            sa.select(TradeProposal).where(TradeProposal.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(f"no trade proposal {ref}")
        return row

    def assessment_for(
        self, session: Session, proposal_ref: str
    ) -> RiskAssessment | None:
        return session.execute(
            sa.select(RiskAssessment).where(
                RiskAssessment.proposal_ref == proposal_ref
            )
        ).scalar_one_or_none()
