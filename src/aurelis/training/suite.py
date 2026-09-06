"""The suite: run a procedure over every scenario and mark it.

One object, and it does one thing — but the bench underneath it is what makes
the milestone affordable. Every engine run is a pure function of
``(scenario, seed, spec)``, so measuring the truth, critiquing with the
incumbent playbook, critiquing with a candidate revision and onboarding
seventeen agents all draw from the same cache. Onboarding a cohort costs what
onboarding one costs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aurelis.engines.synthetic.scenarios import CATALOGUE, Scenario, catalogue_digest
from aurelis.engines.synthetic.truth import (
    REPLICATIONS,
    Bench,
    Presence,
    shared_bench,
)
from aurelis.meetings.taxonomy import MARKET_DEFECTS
from aurelis.meetings.types import ObjectionType
from aurelis.training.critique import Critique, apply_playbook
from aurelis.training.playbook import Playbook
from aurelis.training.scoring import Mark, Scorecard, mark, tally

__all__ = ["SuiteResult", "TrainingSuite", "unscorable_defects"]


@dataclass(frozen=True, slots=True)
class SuiteResult:
    """One procedure, over one catalogue."""

    playbook: str
    playbook_digest: str
    catalogue_digest: str
    replications: int
    marks: tuple[Mark, ...]
    critiques: tuple[Critique, ...]
    score: Scorecard

    def as_payload(self) -> dict[str, Any]:
        return {
            "playbook": self.playbook,
            "playbook_digest": self.playbook_digest,
            "catalogue_digest": self.catalogue_digest,
            "replications": self.replications,
            "score": self.score.as_payload(),
            "marks": [m.as_payload() for m in self.marks],
        }

    def describe(self) -> str:
        return f"{self.playbook}: {self.score.describe()}"


class TrainingSuite:
    """Runs playbooks over the scenario catalogue."""

    __slots__ = ("bench", "scenarios", "replications")

    def __init__(
        self,
        *,
        bench: Bench | None = None,
        scenarios: Sequence[Scenario] = CATALOGUE,
        replications: int = REPLICATIONS,
    ) -> None:
        self.bench = bench or shared_bench()
        self.scenarios = tuple(scenarios)
        self.replications = replications

    def run(self, playbook: Playbook) -> SuiteResult:
        """Critique every scenario, and mark each against measured truth."""
        critiques: list[Critique] = []
        marks: list[Mark] = []
        for scen in self.scenarios:
            truth = self.bench.truth(scen, replications=self.replications)
            critique = apply_playbook(playbook, scen, bench=self.bench)
            critiques.append(critique)
            marks.append(mark(critique, truth))
        return SuiteResult(
            playbook=playbook.describe(),
            playbook_digest=playbook.digest(),
            catalogue_digest=catalogue_digest(),
            replications=self.replications,
            marks=tuple(marks),
            critiques=tuple(critiques),
            score=tally(marks),
        )

    def unscorable(self) -> frozenset[ObjectionType]:
        """Taxonomy entries no scenario can currently grade.

        A coverage hole in the catalogue, reported rather than hidden. An agent
        whose specialty is one of these gets a record that says **not scored**,
        which is the truth, instead of a rate computed from nothing.
        """
        return unscorable_defects(
            self.bench, self.scenarios, replications=self.replications
        )


def unscorable_defects(
    bench: Bench,
    scenarios: Sequence[Scenario] = CATALOGUE,
    *,
    replications: int = REPLICATIONS,
) -> frozenset[ObjectionType]:
    """Defects in the taxonomy that no scenario measures as present."""
    catchable: set[ObjectionType] = set()
    for scen in scenarios:
        truth = bench.truth(scen, replications=replications)
        catchable |= {
            defect
            for defect in truth.defects
            if truth.presence(defect) is Presence.PRESENT
        }
    return frozenset(MARKET_DEFECTS) - catchable
