"""The strategy lifecycle: states, gates, and the one promotion path.

Everything a strategy can become goes through here, and there is exactly one
route to ``VALIDATED``: every registered gate evaluated, every one passed, and a
Strategy Committee decision on the record. No shortcut, no override flag, no
"promote anyway" argument — a promotion that could be forced would make the
gates advisory, and advisory gates are how a book fills with things nobody
checked.

:meth:`Strategies.promote` also stamps ``promoted_at``, which is what arms the
immutability trigger. From that moment the version's spec is frozen at the
database level and a material change has to become a new version. That ordering
matters: the evidence was gathered against a specific composition, and a spec
that could drift afterwards would leave every result row describing something
that no longer exists.

Backward transitions are ordinary. ``DEGRADED`` is reached by a preregistered
rule firing, not by judgement, and it carries the measurement that fired it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import uuid7
from aurelis.platform.ledger.ledger import Ledger
from aurelis.strategy.gates import GateReport, Gates
from aurelis.strategy.states import Portability, StrategyState, may_transition
from aurelis.strategy.tables import (
    Strategy,
    StrategyLineage,
    StrategyPortability,
    StrategyVersion,
)

__all__ = ["PromotionRefused", "Strategies"]


@dataclass(frozen=True, slots=True)
class PromotionRefused:
    """Why a version was not promoted, in enough detail to act on."""

    version_ref: str
    report: GateReport
    reason: str

    def describe(self) -> str:
        return f"{self.version_ref} not promoted: {self.reason}\n{self.report.describe()}"


class Strategies:
    """The lifecycle service. Transitions, promotion, degradation."""

    __slots__ = ("_clock", "_gates", "_ledger")

    def __init__(
        self,
        gates: Gates | None = None,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)
        self._gates = gates or Gates(self._ledger, self._clock)

    # -------------------------------------------------------- transitions

    def transition(
        self,
        session: Session,
        *,
        strategy_ref: str,
        target: StrategyState,
        reason: str,
        actor: str,
        at: dt.datetime | None = None,
    ) -> Strategy:
        """Move a strategy, refusing anything the state machine does not allow."""
        moment = at or self._clock.now()
        strategy = self._strategy(session, strategy_ref)

        if strategy.state == target.value:
            return strategy
        if not may_transition(strategy.state, target.value):
            raise IntegrityViolation(
                f"{strategy_ref} cannot move {strategy.state} -> {target.value}"
            )
        if not reason.strip():
            raise IntegrityViolation(
                "a state change must carry its reason; a strategy that moved "
                "for no recorded cause cannot be reviewed later"
            )

        previous = strategy.state
        strategy.state = target.value
        strategy.state_reason = reason
        if target is StrategyState.RETIRED:
            strategy.retired_at = moment
            strategy.retirement_reason = reason
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.STRATEGY_STATE_CHANGED,
            actor=actor,
            subject=strategy_ref,
            payload={"from": previous, "to": target.value, "reason": reason},
            at=moment,
        )
        return strategy

    def degrade(
        self,
        session: Session,
        *,
        strategy_ref: str,
        tripwire: str,
        observed: str,
        threshold: str,
        actor: str,
        at: dt.datetime | None = None,
    ) -> Strategy:
        """Degrade on a preregistered rule, carrying the measurement.

        Takes the rule and the numbers rather than a free-text reason, because
        `docs/05-lifecycles.md` requires degradation to fire from a rule and not
        from judgement. A signature that accepted only prose would let an
        opinion enter the lifecycle wearing a mechanism's clothes.
        """
        return self.transition(
            session,
            strategy_ref=strategy_ref,
            target=StrategyState.DEGRADED,
            reason=(
                f"{tripwire} fired: observed {observed} against threshold "
                f"{threshold}"
            ),
            actor=actor,
            at=at,
        )

    # --------------------------------------------------------- promotion

    def promote(
        self,
        session: Session,
        *,
        version_ref: str,
        decided_by_meeting: str,
        actor: str,
        at: dt.datetime | None = None,
    ) -> StrategyVersion | PromotionRefused:
        """Validate a version, if and only if every gate passed.

        Returns a :class:`PromotionRefused` rather than raising when the gates
        say no. A refused promotion is an ordinary, expected outcome that the
        record should carry — not an exception for a caller to swallow.
        """
        moment = at or self._clock.now()
        version = self._version(session, version_ref)
        strategy = self._strategy(session, version.strategy_ref)
        report = self._gates.report(session, version_ref)

        if strategy.state != StrategyState.UNDER_REVIEW.value:
            # Refused rather than silently skipped. A version whose strategy
            # never went through research would arrive at VALIDATED without a
            # confirmed finding behind it, which is the exact shortcut the
            # lifecycle exists to prevent -- and an earlier draft of this method
            # simply left the strategy where it was, which looked like success.
            return PromotionRefused(
                version_ref,
                report,
                f"{strategy.ref} is {strategy.state}, not under_review. A "
                "version cannot be validated before its strategy has been "
                "through research",
            )

        if not report.outcomes and not report.unevaluated:
            return PromotionRefused(
                version_ref, report, "no promotion gates were ever registered"
            )
        if report.unevaluated:
            return PromotionRefused(
                version_ref,
                report,
                f"{len(report.unevaluated)} gate(s) not evaluated: "
                + ", ".join(gate.value for gate in report.unevaluated),
            )
        if report.failed:
            failed = ", ".join(outcome.gate.value for outcome in report.failed)
            refusal = PromotionRefused(
                version_ref, report, f"gate(s) {failed} failed"
            )
            self._ledger.append(
                session,
                kind=EventKind.VERSION_PROMOTED,
                actor=actor,
                subject=version_ref,
                payload={
                    "promoted": False,
                    "failed": [o.gate.value for o in report.failed],
                    "detail": [o.detail for o in report.failed],
                    "meeting": decided_by_meeting,
                },
                at=moment,
            )
            return refusal

        version.state = StrategyState.VALIDATED
        version.promoted_at = moment
        version.promoted_by_meeting = decided_by_meeting
        session.flush()

        self.transition(
            session,
            strategy_ref=strategy.ref,
            target=StrategyState.VALIDATED,
            reason=f"{version_ref} passed every registered gate",
            actor=actor,
            at=moment,
        )
        strategy.current_version = version_ref
        session.add(
            StrategyLineage(
                entry_id=uuid7(),
                version_ref=version_ref,
                act="promoted",
                parent_ref=version.supersedes,
                detail=f"every registered gate passed; decided in {decided_by_meeting}",
                author=actor,
                meeting_ref=decided_by_meeting,
                created_at=moment,
            )
        )
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.VERSION_PROMOTED,
            actor=actor,
            subject=version_ref,
            payload={
                "promoted": True,
                "gates": [o.gate.value for o in report.outcomes],
                "meeting": decided_by_meeting,
                "digest": version.spec_digest[:16],
            },
            at=moment,
        )
        return version

    # ------------------------------------------------------- portability

    def record_portability(
        self,
        session: Session,
        *,
        version_ref: str,
        desk: str,
        status: Portability,
        reason: str,
        evidence_ref: str | None = None,
        actor: str = "system",
        at: dt.datetime | None = None,
    ) -> StrategyPortability:
        """Record what a measurement on another desk showed.

        ``PORTED`` and ``REFUTED_HERE`` both require evidence: the whole point
        of the table is that a claim about another market is backed by a run on
        that market rather than by an expectation.
        """
        moment = at or self._clock.now()
        row = session.get(StrategyPortability, (version_ref, desk))
        if row is None:
            raise IntegrityViolation(f"{version_ref} has no portability row for {desk}")
        if status in (Portability.PORTED, Portability.REFUTED_HERE) and not evidence_ref:
            raise IntegrityViolation(
                f"claiming {status.value} on {desk} requires evidence from a run "
                "on that desk. The inherited corpus was measured on one market; "
                "assuming the seventh behaves like the first is the error this "
                "table exists to prevent"
            )

        row.status = status.value
        row.reason = reason
        row.evidence_ref = evidence_ref
        row.assessed_at = moment
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.PORTABILITY_ASSESSED,
            actor=actor,
            subject=version_ref,
            payload={
                "desk": desk,
                "status": status.value,
                "reason": reason,
                "evidence": evidence_ref,
            },
            at=moment,
        )
        return row

    def portability(
        self, session: Session, version_ref: str
    ) -> list[StrategyPortability]:
        return list(
            session.execute(
                sa.select(StrategyPortability)
                .where(StrategyPortability.version_ref == version_ref)
                .order_by(StrategyPortability.desk)
            ).scalars()
        )

    def proven_desks(self, session: Session, version_ref: str) -> tuple[str, ...]:
        """Desks where this version has actually been measured and held.

        The honest answer to "where does this work?". Everything else is
        unproven, inapplicable, or refuted there.
        """
        return tuple(
            row.desk
            for row in self.portability(session, version_ref)
            if row.status in (Portability.NATIVE.value, Portability.PORTED.value)
        )

    # ---------------------------------------------------------- reading

    def version(self, session: Session, ref: str) -> StrategyVersion:
        return self._version(session, ref)

    def strategy(self, session: Session, ref: str) -> Strategy:
        return self._strategy(session, ref)

    def versions(self, session: Session, strategy_ref: str) -> list[StrategyVersion]:
        return list(
            session.execute(
                sa.select(StrategyVersion)
                .where(StrategyVersion.strategy_ref == strategy_ref)
                .order_by(StrategyVersion.n)
            ).scalars()
        )

    def validated(self, session: Session) -> list[StrategyVersion]:
        return list(
            session.execute(
                sa.select(StrategyVersion)
                .where(StrategyVersion.promoted_at.is_not(None))
                .order_by(StrategyVersion.promoted_at)
            ).scalars()
        )

    def all(self, session: Session) -> list[Strategy]:
        return list(
            session.execute(sa.select(Strategy).order_by(Strategy.ref)).scalars()
        )

    @staticmethod
    def _strategy(session: Session, ref: str) -> Strategy:
        row = session.execute(
            sa.select(Strategy).where(Strategy.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(f"no strategy {ref}")
        return row

    @staticmethod
    def _version(session: Session, ref: str) -> StrategyVersion:
        row = session.execute(
            sa.select(StrategyVersion).where(StrategyVersion.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(f"no strategy version {ref}")
        return row

