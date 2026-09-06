"""Synthetic research scenarios: worlds where the answer is known.

Not a market simulator, and no research conclusion about any real market may
be drawn from anything here. These worlds exist so the company can be
*scored* — on catching planted defects, and on not finding effects in worlds
that have none (ADR-0005).

A scenario score is **institutional competence, not market truth**. An agent
calibrated on planted effects may still be miscalibrated on real markets, and
every report of one has to say which it is.
"""

from __future__ import annotations

from aurelis.engines.synthetic.scenarios import (
    CATALOGUE,
    Scenario,
    catalogue_digest,
    scenario,
)
from aurelis.engines.synthetic.truth import (
    DEFECT_THRESHOLD,
    EFFECT_THRESHOLD,
    REPLICATIONS,
    Bench,
    Presence,
    Reading,
    ScenarioTruth,
    measure_catalogue,
    measure_truth,
    shared_bench,
)
from aurelis.engines.synthetic.world import Death, SyntheticWorld, WorldRecipe

__all__ = [
    "CATALOGUE",
    "DEFECT_THRESHOLD",
    "EFFECT_THRESHOLD",
    "REPLICATIONS",
    "Bench",
    "Death",
    "Presence",
    "Reading",
    "Scenario",
    "ScenarioTruth",
    "SyntheticWorld",
    "WorldRecipe",
    "catalogue_digest",
    "measure_catalogue",
    "measure_truth",
    "scenario",
    "shared_bench",
]
