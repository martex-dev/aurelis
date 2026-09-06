"""The regression gate: a revision that scores worse does not ship.

A playbook is the company's critique procedure, and it will be edited — by
people now, by the Org Development Lead at M11. The question every edit raises
is the one nobody can answer from reading it: **did that make us better at
finding real defects, or just better at raising objections?**

The gate answers it with the same twelve worlds. A candidate is run over the
suite and compared with the incumbent on three axes:

* it must not catch **fewer** real defects,
* it must not raise **more** false alarms,
* it must not get **fewer** effect calls right.

Comparison is on counts, not rates. Rates hide the denominator, and a revision
that narrowed its checks so that it faced fewer questions could improve every
rate while finding less — which is precisely the change this gate exists to
refuse.

It runs in CI (``aurelis training regression``), offline and free, because the
whole suite is deterministic arithmetic over generated worlds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aurelis.training.playbook import INCUMBENT, Playbook
from aurelis.training.suite import SuiteResult, TrainingSuite

__all__ = ["RegressionVerdict", "gate"]


@dataclass(frozen=True, slots=True)
class RegressionVerdict:
    """Whether a revision may ship, and what changed."""

    incumbent: SuiteResult
    candidate: SuiteResult
    regressions: tuple[str, ...]
    improvements: tuple[str, ...]

    @property
    def ships(self) -> bool:
        return not self.regressions

    def as_payload(self) -> dict[str, Any]:
        return {
            "incumbent": self.incumbent.playbook,
            "candidate": self.candidate.playbook,
            "incumbent_score": self.incumbent.score.as_payload(),
            "candidate_score": self.candidate.score.as_payload(),
            "regressions": list(self.regressions),
            "improvements": list(self.improvements),
            "ships": self.ships,
        }

    def describe(self) -> str:
        if self.ships:
            gained = "; ".join(self.improvements) or "no measured change"
            return f"{self.candidate.playbook} may ship — {gained}"
        return f"{self.candidate.playbook} refused — " + "; ".join(self.regressions)


def gate(
    candidate: Playbook,
    *,
    incumbent: Playbook = INCUMBENT,
    suite: TrainingSuite | None = None,
) -> RegressionVerdict:
    """Run both procedures over the suite and compare them."""
    suite = suite or TrainingSuite()
    before = suite.run(incumbent)
    after = suite.run(candidate)

    regressions: list[str] = []
    improvements: list[str] = []

    for label, old, new, higher_is_better in (
        ("caught", before.score.caught, after.score.caught, True),
        ("false alarms", before.score.false_alarms, after.score.false_alarms, False),
        (
            "effect calls right",
            before.score.effect_correct,
            after.score.effect_correct,
            True,
        ),
    ):
        if new == old:
            continue
        better = new > old if higher_is_better else new < old
        line = f"{label} {old} -> {new}"
        (improvements if better else regressions).append(line)

    return RegressionVerdict(before, after, tuple(regressions), tuple(improvements))
