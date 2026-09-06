"""Applying a playbook to one scenario: what a critic actually sees.

The asymmetry with :mod:`aurelis.engines.synthetic.truth` is the whole design.
Truth gets twenty-four independent draws of a world. A critic gets **seed
zero** — one history, which is what a researcher has. It can therefore be right
by luck and wrong by bad luck, exactly as in the job, and a procedure that
scores well across twelve scenarios has earned it rather than been handed it.

Seed zero is never one of the draws that settles the answer, so the question
does not contain its own answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.engines.synthetic.scenarios import Scenario
from aurelis.engines.synthetic.truth import Bench, varied_spec
from aurelis.meetings.taxonomy import LOWER_IS_BETTER, DefectKind, defects_for
from aurelis.meetings.types import ObjectionType
from aurelis.training.playbook import Playbook

__all__ = ["CRITIC_SEED", "Critique", "apply_playbook"]

CRITIC_SEED = 0
"""The one history a critic is shown. Truth uses 1..N and never this one."""



@dataclass(frozen=True, slots=True)
class Critique:
    """What one procedure said about one scenario, on one draw."""

    scenario_id: str
    playbook: str
    alleged: frozenset[ObjectionType]
    calls_effect_real: bool
    observed: Decimal
    """The headline metric of the presented run, on the draw the critic saw."""

    considered: frozenset[ObjectionType]
    """Defects the procedure actually tested. A defect it never looked at is
    not a silence to its credit."""

    detail: dict[str, str]

    def as_payload(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "playbook": self.playbook,
            "alleged": sorted(d.value for d in self.alleged),
            "considered": sorted(d.value for d in self.considered),
            "calls_effect_real": self.calls_effect_real,
            "observed": str(self.observed),
            "detail": dict(self.detail),
        }


def apply_playbook(
    playbook: Playbook, scen: Scenario, *, bench: Bench, seed: int = CRITIC_SEED
) -> Critique:
    """Run one procedure over one scenario and record what it alleges."""
    presented = scen.presented()
    observed = bench.value(scen, presented, seed=seed)
    worse_is_larger = scen.metric in LOWER_IS_BETTER
    calls_real = (
        observed < -playbook.effect_threshold
        if worse_is_larger
        else observed > playbook.effect_threshold
    )

    applicable = {d.type: d for d in defects_for(presented)}
    alleged: set[ObjectionType] = set()
    considered: set[ObjectionType] = set()
    detail: dict[str, str] = {}

    for check in playbook.checks:
        defect = applicable.get(check.defect)
        if defect is None:
            # The taxonomy says this test means nothing against this
            # specification. Not a silence, and not a miss.
            continue
        considered.add(check.defect)
        varied = varied_spec(scen, check.defect, observed)
        under_test = bench.value(scen, varied, seed=seed)
        degradation = (
            under_test - observed if worse_is_larger else observed - under_test
        )
        moved = degradation >= check.degradation
        if defect.kind is DefectKind.CORRECTIVE:
            raises = moved
            why = f"degradation {degradation:+.4f} vs {check.degradation}"
        else:
            survived = (
                under_test < -check.survives_below
                if worse_is_larger
                else under_test > check.survives_below
            )
            raises = moved and calls_real and not survived
            why = (
                f"degradation {degradation:+.4f} vs {check.degradation}; "
                f"stressed {under_test:+.4f} vs {check.survives_below}; "
                f"had a result: {calls_real}"
            )
        if raises:
            alleged.add(check.defect)
        detail[check.defect.value] = why

    return Critique(
        scenario_id=scen.scenario_id,
        playbook=playbook.describe(),
        alleged=frozenset(alleged),
        calls_effect_real=calls_real,
        observed=observed,
        considered=frozenset(considered),
        detail=detail,
    )
