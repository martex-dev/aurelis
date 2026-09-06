"""Playbooks: the critique procedure a charter issues, versioned.

A playbook is not a prompt. It is an ordered set of **checks**, each naming one
defect from the closed taxonomy and the thresholds at which that defect is
worth alleging. Applying it is arithmetic: run the specification, run the
mechanical test the taxonomy builds for the defect, compare.

That is what makes the whole milestone possible. A procedure written as prose
cannot be scored, cannot be versioned meaningfully, and cannot be regressed —
a revision either reads better or it does not. A procedure written as
thresholds can be run against twelve worlds with known answers and told whether
it got better.

**What a playbook is not.** It is not the agent's judgement. At M10 an agent's
onboarding score is a score for the procedure its charters issue it, and the
report says so in those words. What the harness proves today is that the
company can measure a procedure and refuse to ship a worse one; what it will
measure when agents reason for themselves is the same thing, through the same
harness, with the agent in place of the thresholds.

Two thresholds per check, because the taxonomy has two kinds of test
(:class:`~aurelis.meetings.taxonomy.DefectKind`):

``degradation``
    How far the varied run must fall before the defect is worth raising.
    Sufficient on its own for a **corrective** test, where the varied run is
    simply the truer one.

``survives_below``
    For a **stress** test only. The defect is that the *conclusion* did not
    survive, so the stressed run must land below this. A critic that alleged
    understated costs because a number moved would be alleging it against every
    specification that trades.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from aurelis.core.canonical import sha256_of
from aurelis.meetings.taxonomy import MARKET_DEFECTS, DefectKind
from aurelis.meetings.types import ObjectionType

__all__ = [
    "INCUMBENT",
    "SPECIALTIES",
    "Check",
    "Playbook",
    "playbook_for",
    "specialty_of",
]


@dataclass(frozen=True, slots=True)
class Check:
    """One defect, and when this procedure says it is worth alleging."""

    defect: ObjectionType
    degradation: Decimal
    survives_below: Decimal = Decimal("0.01")

    @property
    def kind(self) -> DefectKind:
        return MARKET_DEFECTS[self.defect].kind

    def as_payload(self) -> dict[str, Any]:
        return {
            "defect": self.defect.value,
            "degradation": str(self.degradation),
            "survives_below": str(self.survives_below),
        }


@dataclass(frozen=True, slots=True)
class Playbook:
    """A named, versioned critique procedure."""

    playbook_id: str
    version: str
    title: str
    checks: tuple[Check, ...]
    effect_threshold: Decimal = Decimal("0.01")
    """Above this, the procedure calls the presented result a real effect."""

    note: str = ""

    @property
    def covers(self) -> frozenset[ObjectionType]:
        return frozenset(check.defect for check in self.checks)

    def check_for(self, defect: ObjectionType) -> Check | None:
        return next((c for c in self.checks if c.defect is defect), None)

    def restricted_to(self, defects: Iterable[ObjectionType]) -> Playbook:
        """The same procedure, cut down to one specialty's defects.

        A Data Auditor is not asked about capacity and is not scored on it.
        Restricting the procedure rather than filtering the score afterwards
        means the agent is never *shown* a question outside its remit, which is
        the difference between a specialty and a marking scheme.
        """
        wanted = frozenset(defects)
        return replace(
            self, checks=tuple(c for c in self.checks if c.defect in wanted)
        )

    def revised(
        self,
        defect: ObjectionType,
        *,
        degradation: Decimal | None = None,
        survives_below: Decimal | None = None,
    ) -> Playbook:
        """A candidate revision. What the regression gate is given."""
        checks = tuple(
            Check(
                c.defect,
                c.degradation if degradation is None else degradation,
                c.survives_below if survives_below is None else survives_below,
            )
            if c.defect is defect
            else c
            for c in self.checks
        )
        major, _, minor = self.version.partition(".")
        return replace(
            self,
            version=f"{major}.{int(minor or 0) + 1}",
            checks=checks,
            note=f"revision of {self.playbook_id}@{self.version}",
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "playbook_id": self.playbook_id,
            "version": self.version,
            "effect_threshold": str(self.effect_threshold),
            "checks": [c.as_payload() for c in self.checks],
        }

    def digest(self) -> str:
        return sha256_of(self.as_payload())

    def describe(self) -> str:
        return f"{self.playbook_id}@{self.version}"


INCUMBENT = Playbook(
    "critique.market_defects",
    "1.0",
    "How this company reads a backtest it did not run",
    checks=(
        Check(ObjectionType.SURVIVORSHIP, Decimal("0.05")),
        Check(ObjectionType.LOOKAHEAD, Decimal("0.05")),
        Check(ObjectionType.COST_UNDERSTATED, Decimal("0.02")),
        Check(ObjectionType.REGIME_SPECIFIC, Decimal("0.02")),
        Check(ObjectionType.CAPACITY_IGNORED, Decimal("0.02")),
    ),
    note=(
        "The thresholds are the company's, not a fact about markets. They "
        "say how large a difference has to be before this company is willing "
        "to spend a meeting on it."
    ),
)
"""The shipped procedure. What a revision is measured against."""


SPECIALTIES: dict[str, frozenset[ObjectionType]] = {
    # Strategy Lab: the roles whose whole job is finding the hole.
    "strategy.critic": frozenset(MARKET_DEFECTS),
    "strategy.adversarial": frozenset(MARKET_DEFECTS),
    "strategy.validation": frozenset(MARKET_DEFECTS),
    "strategy.robustness": frozenset(
        {
            ObjectionType.COST_UNDERSTATED,
            ObjectionType.REGIME_SPECIFIC,
            ObjectionType.CAPACITY_IGNORED,
        }
    ),
    "strategy.replication": frozenset({ObjectionType.REGIME_SPECIFIC}),
    # Audit: independent, and narrower on purpose.
    "audit.backtest": frozenset(
        {
            ObjectionType.LOOKAHEAD,
            ObjectionType.SURVIVORSHIP,
            ObjectionType.COST_UNDERSTATED,
        }
    ),
    "audit.data": frozenset({ObjectionType.SURVIVORSHIP}),
    "audit.research": frozenset(
        {ObjectionType.LOOKAHEAD, ObjectionType.REGIME_SPECIFIC}
    ),
    # Research: the people who will write the specification in the first place.
    "research.backtest": frozenset(
        {ObjectionType.LOOKAHEAD, ObjectionType.COST_UNDERSTATED}
    ),
    "research.statistical": frozenset({ObjectionType.REGIME_SPECIFIC}),
    "research.quant": frozenset(
        {ObjectionType.COST_UNDERSTATED, ObjectionType.REGIME_SPECIFIC}
    ),
    "intel.regime_analyst": frozenset({ObjectionType.REGIME_SPECIFIC}),
    "risk.stress_testing": frozenset(
        {ObjectionType.CAPACITY_IGNORED, ObjectionType.COST_UNDERSTATED}
    ),
    "trading.post_trade": frozenset({ObjectionType.COST_UNDERSTATED}),
    # Governance.
    "gov.skeptic": frozenset(MARKET_DEFECTS),
    "gov.peer_reviewer": frozenset(MARKET_DEFECTS),
    "gov.replication_officer": frozenset({ObjectionType.REGIME_SPECIFIC}),
}
"""Which charters are answerable for which planted defects.

Deliberately partial. A Company Manager has no scenario specialty, and its
onboarding record says **not scored** rather than a hundred percent of nothing.
Inventing a specialty for every charter so that every agent gets a number would
put fiction in the permanent record of two thirds of the company.
"""


def specialty_of(coverage: Iterable[str]) -> frozenset[ObjectionType]:
    """The defects an agent holding this coverage is answerable for."""
    found: set[ObjectionType] = set()
    for charter_id in coverage:
        found |= SPECIALTIES.get(charter_id, frozenset())
    return frozenset(found)


def playbook_for(
    coverage: Iterable[str], *, base: Playbook = INCUMBENT
) -> Playbook | None:
    """The procedure this coverage is issued, or ``None`` if it has no specialty."""
    specialty = specialty_of(coverage)
    if not specialty:
        return None
    return base.restricted_to(specialty)
