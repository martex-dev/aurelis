"""Deriving a verdict, deterministically, from criteria registered beforehand.

No model chooses a verdict. It is a pure function of two things that were both
fixed before the run existed — the criteria in the locked registration, and the
interval the engine computed — and the same inputs always give the same answer.

That is the entire defence against HARKing. Deciding what counts as success
after seeing the numbers is the single most effective way to manufacture a
false discovery, and here it is not discouraged, it is unreachable: the
criteria are hashed and immutable before a run may exist, and this function
never sees anything else.

The order of the checks matters
-------------------------------

**Power is tested first.** If the interval is too wide to distinguish the
claimed effect from nothing, the answer is UNDERPOWERED and no other question
is asked. Running the pass test first would let a wide interval whose point
estimate happens to land above the bar be reported as a confirmation, which is
precisely how confident nothing accumulates.

**Refutation needs the interval to exclude the claim**, not merely to miss it.
A point estimate below the bar with an interval that still contains it means
the data did not settle the question — INCONCLUSIVE — and calling that a
refutation would be as unearned as calling it a confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from aurelis.engines.protocol import MetricSet, UnsupportedMetric
from aurelis.research.states import Verdict

__all__ = ["Criterion", "VerdictReport", "derive_verdict", "parse_criteria"]

_COMPARISONS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
}

_BOUNDS = ("point", "low", "high")


@dataclass(frozen=True, slots=True)
class Criterion:
    """One registered pass condition.

    ``on`` chooses which end of the interval is tested. ``low`` is the strict
    reading — "even the pessimistic end clears the bar" — and is what a
    confirmatory registration should normally use. ``point`` is available and
    weaker, and the registration says which was chosen, before the run.
    """

    metric: str
    comparison: str
    value: Decimal
    on: str = "low"

    def describe(self) -> str:
        return f"{self.metric}.{self.on} {self.comparison} {self.value}"

    def evaluate(self, metrics: MetricSet) -> tuple[bool, str]:
        try:
            metric = metrics.get(self.metric)
        except UnsupportedMetric as error:
            return False, str(error)

        if self.on == "point":
            observed = metric.value
        elif self.on == "low":
            if metric.low is None:
                return False, f"{self.metric} has no interval, so {self.on} cannot be tested"
            observed = metric.low
        else:
            if metric.high is None:
                return False, f"{self.metric} has no interval, so {self.on} cannot be tested"
            observed = metric.high

        holds = _COMPARISONS[self.comparison](observed, self.value)
        return holds, f"{self.metric}.{self.on}={observed} {self.comparison} {self.value}"


@dataclass(frozen=True, slots=True)
class VerdictReport:
    """A verdict and the arithmetic that produced it."""

    verdict: Verdict
    reason: str
    checks: tuple[str, ...] = field(default_factory=tuple)

    def as_payload(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "checks": list(self.checks),
        }


def parse_criteria(payload: list[dict[str, Any]]) -> tuple[Criterion, ...]:
    """Read registered criteria, refusing anything malformed.

    Refusing rather than skipping: a criterion the system could not parse
    would silently drop a condition the registration promised to test, and the
    result would look like it had passed a bar nobody checked.
    """
    criteria: list[Criterion] = []
    for index, entry in enumerate(payload):
        try:
            comparison = str(entry["comparison"])
            on = str(entry.get("on", "low"))
            if comparison not in _COMPARISONS:
                raise ValueError(f"unknown comparison {comparison!r}")
            if on not in _BOUNDS:
                raise ValueError(f"unknown bound {on!r}; expected one of {_BOUNDS}")
            criteria.append(
                Criterion(
                    metric=str(entry["metric"]),
                    comparison=comparison,
                    value=Decimal(str(entry["value"])),
                    on=on,
                )
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as error:
            raise ValueError(
                f"criterion {index} is malformed ({error}); a registration whose "
                "criteria cannot be parsed cannot be evaluated, and treating it "
                "as satisfied would be worse than refusing it"
            ) from error
    if not criteria:
        raise ValueError(
            "a registration must declare at least one pass criterion; without "
            "one there is nothing the run could fail"
        )
    return tuple(criteria)


def derive_verdict(
    metrics: MetricSet,
    criteria: tuple[Criterion, ...],
    *,
    minimum_effect: Decimal,
    primary_metric: str,
) -> VerdictReport:
    """The verdict, from the registered criteria and the computed interval.

    ``minimum_effect`` is the smallest effect the registration said would be
    worth caring about. It is what makes the power test possible: an interval
    wider than the effect you set out to detect cannot answer the question you
    asked, however the point estimate happens to fall.
    """
    checks: list[str] = []

    # 0. Did the run produce what was registered?
    if not metrics.has(primary_metric):
        return VerdictReport(
            Verdict.INVALID,
            f"the run produced no {primary_metric!r}, which the registration named "
            "as its primary metric",
        )
    primary = metrics.get(primary_metric)

    # 1. Power, before anything else.
    if not primary.has_interval:
        return VerdictReport(
            Verdict.UNDERPOWERED,
            f"{primary_metric} was reported without an interval, so the data "
            "cannot distinguish the claimed effect from nothing",
        )
    width = primary.width
    assert width is not None
    if width > minimum_effect * Decimal(2):
        return VerdictReport(
            Verdict.UNDERPOWERED,
            f"the {primary_metric} interval is {width} wide against a minimum "
            f"effect of {minimum_effect}; this design could not have detected "
            "the effect it set out to find",
            (f"width={width} > 2*minimum_effect={minimum_effect * Decimal(2)}",),
        )
    checks.append(f"power: width={width} <= 2*minimum_effect={minimum_effect * Decimal(2)}")

    # 2. Every registered criterion.
    failures: list[str] = []
    for criterion in criteria:
        holds, detail = criterion.evaluate(metrics)
        checks.append(f"{'PASS' if holds else 'FAIL'}: {detail}")
        if not holds:
            failures.append(detail)

    if not failures:
        return VerdictReport(
            Verdict.CONFIRMED,
            f"every registered criterion held ({len(criteria)} of {len(criteria)})",
            tuple(checks),
        )

    # 3. Refutation requires the interval to EXCLUDE the claim, not miss it.
    excluded = primary.high is not None and primary.high < minimum_effect
    if excluded:
        return VerdictReport(
            Verdict.REFUTED,
            f"the {primary_metric} interval tops out at {primary.high}, below the "
            f"minimum effect of {minimum_effect}; an effect that large is ruled out",
            tuple(checks),
        )

    return VerdictReport(
        Verdict.INCONCLUSIVE,
        f"{len(failures)} criterion/criteria did not hold, but the interval still "
        f"contains the minimum effect of {minimum_effect}; the data did not settle "
        "the question either way",
        tuple(checks),
    )
