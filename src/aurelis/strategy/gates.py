"""Promotion gates: criteria fixed before they are evaluated.

The same rule as a preregistration, applied to deployment. A gate whose
threshold could be written after the measurement is not a gate — it is a
description of what happened, and a company that wrote its gates that way would
promote everything.

So :func:`register` stores the criterion with a digest and a timestamp, and
:func:`evaluate` compares an observation against the *stored* criterion. A
trigger refuses an evaluation that predates its registration, and the unique
constraint refuses a second registration of the same gate on the same version.

Two gates deserve their own note.

**Gate B** exists because a strategy that loses to buy-and-hold is not a
strategy. It is the cheapest way to catch an "edge" that is really beta.

**Gate C** exists because the best individual strategy is not automatically a
portfolio component. A version can pass every solo test and still add nothing
to a book it correlates with, and gate C is where that gets caught — which is
also why the M8 acceptance criterion names it specifically.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import uuid7
from aurelis.platform.ledger.chain import payload_hash
from aurelis.platform.ledger.ledger import Ledger
from aurelis.strategy.states import Gate
from aurelis.strategy.tables import PromotionGate

__all__ = ["GATE_OWNERS", "GateOutcome", "GateReport", "Gates"]

GATE_OWNERS: dict[Gate, str] = {
    Gate.A_STATISTICAL: "research.statistical",
    Gate.B_BENCHMARK: "strategy.validation",
    Gate.C_INDEPENDENCE: "risk.correlation",
    Gate.D_INTEGRITY: "audit.backtest",
    Gate.E_REPLICATION: "strategy.replication",
    Gate.F_CUSTODY: "gov.custodian",
    Gate.G_CAPACITY: "risk.capital_allocation",
}
"""Which charter owns each gate.

Recorded on the row so "who was supposed to check this?" is answerable years
later, and so a gate evaluated by the wrong role is visible rather than
indistinguishable.
"""

_COMPARISONS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
}


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """One gate's result and the arithmetic behind it."""

    gate: Gate
    passed: bool
    observed: str
    criterion: str
    detail: str

    def describe(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"{mark} {self.gate.value}: {self.detail}"


@dataclass(frozen=True, slots=True)
class GateReport:
    """Every gate on a version, and whether it may be promoted."""

    version_ref: str
    outcomes: tuple[GateOutcome, ...]
    unevaluated: tuple[Gate, ...]

    @property
    def failed(self) -> tuple[GateOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.passed)

    @property
    def clear(self) -> bool:
        """Every registered gate evaluated, and every one passed."""
        return not self.failed and not self.unevaluated

    def describe(self) -> str:
        lines = [outcome.describe() for outcome in self.outcomes]
        if self.unevaluated:
            lines.append(
                "NOT EVALUATED: "
                + ", ".join(gate.value for gate in self.unevaluated)
            )
        return "\n".join(lines) or "no gates registered"


class Gates:
    """Registering criteria, then evaluating against them."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def register(
        self,
        session: Session,
        *,
        version_ref: str,
        gate: Gate,
        metric: str,
        comparison: str,
        value: Decimal,
        registered_by: str,
        note: str = "",
        at: dt.datetime | None = None,
    ) -> PromotionGate:
        """Fix a criterion. Once written it is what the gate means."""
        if comparison not in _COMPARISONS:
            raise IntegrityViolation(
                f"unknown comparison {comparison!r}; a gate must state a "
                "check that can actually be run"
            )
        existing = session.execute(
            sa.select(PromotionGate).where(
                PromotionGate.version_ref == version_ref,
                PromotionGate.gate == gate.value,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise IntegrityViolation(
                f"gate {gate.value} is already registered for {version_ref}. "
                "Re-registering after a disappointing measurement is how a "
                "threshold becomes a description"
            )

        moment = at or self._clock.now()
        criterion = {
            "metric": metric,
            "comparison": comparison,
            "value": str(value),
            "note": note,
        }
        row = PromotionGate(
            gate_id=uuid7(),
            version_ref=version_ref,
            gate=gate.value,
            criterion=criterion,
            criterion_digest=payload_hash(criterion),
            owner_charter=GATE_OWNERS[gate],
            registered_at=moment,
            registered_by=registered_by,
        )
        session.add(row)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.GATE_REGISTERED,
            actor=registered_by,
            subject=version_ref,
            payload={
                "gate": gate.value,
                "metric": metric,
                "comparison": comparison,
                "value": str(value),
                "owner": GATE_OWNERS[gate],
            },
            at=moment,
        )
        return row

    def evaluate(
        self,
        session: Session,
        *,
        version_ref: str,
        gate: Gate,
        observed: Decimal,
        evaluated_by: str,
        evidence_ref: str | None = None,
        at: dt.datetime | None = None,
    ) -> GateOutcome:
        """Compare a measurement against the criterion registered earlier."""
        moment = at or self._clock.now()
        row = session.execute(
            sa.select(PromotionGate).where(
                PromotionGate.version_ref == version_ref,
                PromotionGate.gate == gate.value,
            )
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(
                f"gate {gate.value} was never registered for {version_ref}; "
                "a criterion written now would be chosen knowing the answer"
            )
        if row.evaluated_at is not None:
            raise IntegrityViolation(
                f"gate {gate.value} on {version_ref} was already evaluated at "
                f"{row.evaluated_at.isoformat()}"
            )

        criterion = dict(row.criterion)
        comparison = str(criterion["comparison"])
        try:
            bound = Decimal(str(criterion["value"]))
        except InvalidOperation as error:  # pragma: no cover - CHECK-guarded
            raise IntegrityViolation(f"gate {gate.value} has no numeric bound") from error

        passed = bool(_COMPARISONS[comparison](observed, bound))
        row.evaluated_at = moment
        row.evaluated_by = evaluated_by
        row.passed = passed
        row.observed = str(observed)
        row.evidence_ref = evidence_ref
        session.flush()

        detail = (
            f"{criterion['metric']} measured {observed}; required "
            f"{comparison} {bound}"
        )
        self._ledger.append(
            session,
            kind=EventKind.GATE_EVALUATED,
            actor=evaluated_by,
            subject=version_ref,
            payload={
                "gate": gate.value,
                "observed": str(observed),
                "passed": passed,
                "criterion_digest": row.criterion_digest[:16],
                "evidence": evidence_ref,
            },
            at=moment,
        )
        return GateOutcome(
            gate=gate,
            passed=passed,
            observed=str(observed),
            criterion=f"{comparison} {bound}",
            detail=detail,
        )

    def report(self, session: Session, version_ref: str) -> GateReport:
        rows = list(
            session.execute(
                sa.select(PromotionGate)
                .where(PromotionGate.version_ref == version_ref)
                .order_by(PromotionGate.gate)
            ).scalars()
        )
        outcomes: list[GateOutcome] = []
        unevaluated: list[Gate] = []

        for row in rows:
            gate = Gate(row.gate)
            if row.evaluated_at is None or row.passed is None:
                unevaluated.append(gate)
                continue
            criterion = dict(row.criterion)
            outcomes.append(
                GateOutcome(
                    gate=gate,
                    passed=bool(row.passed),
                    observed=row.observed,
                    criterion=f"{criterion.get('comparison')} {criterion.get('value')}",
                    detail=(
                        f"{criterion.get('metric')} measured {row.observed}; "
                        f"required {criterion.get('comparison')} "
                        f"{criterion.get('value')}"
                    ),
                )
            )
        return GateReport(version_ref, tuple(outcomes), tuple(unevaluated))


def default_criteria(desk: str) -> dict[Gate, dict[str, Any]]:
    """A starting set, per desk. Registered explicitly, never applied silently.

    Returned as data for a caller to register, rather than written here, so
    that every gate on a version has a named registrar and a timestamp. A
    default that installed itself would be a criterion nobody chose.
    """
    return {
        Gate.A_STATISTICAL: {
            "metric": "deflated_sharpe",
            "comparison": "gte",
            "value": Decimal("0.95"),
            "note": f"against the lifetime trial count, not {desk}'s family",
        },
        Gate.B_BENCHMARK: {
            "metric": "excess_sharpe_over_benchmark",
            "comparison": "gt",
            "value": Decimal("0"),
            "note": "same instruments, window and costs as the desk benchmark",
        },
        Gate.C_INDEPENDENCE: {
            "metric": "max_correlation_with_deployed",
            "comparison": "lt",
            "value": Decimal("0.5"),
            "note": "against every currently allocated version",
        },
        Gate.D_INTEGRITY: {
            "metric": "open_critical_objections",
            "comparison": "eq",
            "value": Decimal("0"),
            "note": "point-in-time universe and realistic costs required",
        },
        Gate.E_REPLICATION: {
            "metric": "surviving_replications",
            "comparison": "gte",
            "value": Decimal("1"),
            "note": "with a declared variation",
        },
        Gate.F_CUSTODY: {
            "metric": "sealed_queries_used",
            "comparison": "lte",
            "value": Decimal("1"),
            "note": "and it must have passed",
        },
        Gate.G_CAPACITY: {
            "metric": "capacity_over_intended_allocation",
            "comparison": "gte",
            "value": Decimal("1"),
            "note": "at realistic participation",
        },
    }
