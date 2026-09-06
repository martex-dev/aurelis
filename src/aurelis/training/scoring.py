"""Marking a critique against measured truth.

Four outcomes per defect, and the fourth is the one that keeps the suite
honest:

``caught``        alleged, and the defect is really there
``missed``        really there, and not alleged
``false alarm``   alleged, and measurement says it is not there
``unscored``      measurement could not settle it, so neither can the mark

Nothing is graded against a scenario's *intent*. If a plant did not take, the
critic that stayed quiet was right, and it is marked right.

Rates are ``None`` rather than zero when the denominator is empty. A specialty
with no planted defects anywhere in the suite has a catch rate of *nothing at
all*, and reporting that as 0% would fail an agent for a gap in the catalogue,
while reporting it as 100% would pass one on no evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.engines.synthetic.truth import Presence, ScenarioTruth
from aurelis.meetings.types import ObjectionType
from aurelis.training.critique import Critique

__all__ = ["Mark", "Scorecard", "mark", "tally"]

_ZERO = Decimal("0")


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


@dataclass(frozen=True, slots=True)
class Mark:
    """One scenario, graded."""

    scenario_id: str
    caught: frozenset[ObjectionType]
    missed: frozenset[ObjectionType]
    false_alarms: frozenset[ObjectionType]
    true_silences: frozenset[ObjectionType]
    unscored: frozenset[ObjectionType]
    effect_call: str
    """``correct`` | ``wrong`` | ``unscored``."""

    observed: Decimal
    note: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "caught": sorted(d.value for d in self.caught),
            "missed": sorted(d.value for d in self.missed),
            "false_alarms": sorted(d.value for d in self.false_alarms),
            "true_silences": sorted(d.value for d in self.true_silences),
            "unscored": sorted(d.value for d in self.unscored),
            "effect_call": self.effect_call,
            "observed": str(self.observed),
            "note": self.note,
        }


def mark(critique: Critique, truth: ScenarioTruth) -> Mark:
    """Grade one critique against what replication established."""
    considered = critique.considered
    caught: set[ObjectionType] = set()
    missed: set[ObjectionType] = set()
    false_alarms: set[ObjectionType] = set()
    silences: set[ObjectionType] = set()
    unscored: set[ObjectionType] = set()

    for defect in considered:
        presence = truth.presence(defect)
        alleged = defect in critique.alleged
        if presence is Presence.UNDETERMINED:
            unscored.add(defect)
        elif presence is Presence.PRESENT:
            (caught if alleged else missed).add(defect)
        else:
            (false_alarms if alleged else silences).add(defect)

    if truth.effect_present is Presence.UNDETERMINED:
        effect_call = "unscored"
    else:
        wanted = truth.effect_present is Presence.PRESENT
        effect_call = "correct" if critique.calls_effect_real == wanted else "wrong"

    return Mark(
        scenario_id=truth.scenario_id,
        caught=frozenset(caught),
        missed=frozenset(missed),
        false_alarms=frozenset(false_alarms),
        true_silences=frozenset(silences),
        unscored=frozenset(unscored),
        effect_call=effect_call,
        observed=critique.observed,
    )


@dataclass(frozen=True, slots=True)
class Scorecard:
    """A whole suite, tallied."""

    scenarios: int
    caught: int
    missed: int
    false_alarms: int
    true_silences: int
    effect_correct: int
    effect_wrong: int
    effect_unscored: int
    unscored_items: int

    @property
    def catch_rate(self) -> Decimal | None:
        """Of the defects really there, how many were raised."""
        return _rate(self.caught, self.caught + self.missed)

    @property
    def false_alarm_rate(self) -> Decimal | None:
        """Of the defects that were not there, how many were raised anyway."""
        return _rate(self.false_alarms, self.false_alarms + self.true_silences)

    @property
    def effect_accuracy(self) -> Decimal | None:
        settled = self.effect_correct + self.effect_wrong
        return _rate(self.effect_correct, settled)

    @property
    def planted(self) -> int:
        return self.caught + self.missed

    def as_payload(self) -> dict[str, Any]:
        return {
            "scenarios": self.scenarios,
            "caught": self.caught,
            "missed": self.missed,
            "false_alarms": self.false_alarms,
            "true_silences": self.true_silences,
            "effect_correct": self.effect_correct,
            "effect_wrong": self.effect_wrong,
            "effect_unscored": self.effect_unscored,
            "unscored_items": self.unscored_items,
            "catch_rate": _text(self.catch_rate),
            "false_alarm_rate": _text(self.false_alarm_rate),
            "effect_accuracy": _text(self.effect_accuracy),
        }

    def describe(self) -> str:
        return (
            f"caught {self.caught}/{self.planted}, "
            f"false alarms {self.false_alarms}/"
            f"{self.false_alarms + self.true_silences}, "
            f"effect calls {self.effect_correct}/"
            f"{self.effect_correct + self.effect_wrong}"
        )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def tally(marks: Iterable[Mark] | Sequence[Mark]) -> Scorecard:
    """Add up a suite's marks."""
    rows = list(marks)
    return Scorecard(
        scenarios=len(rows),
        caught=sum(len(m.caught) for m in rows),
        missed=sum(len(m.missed) for m in rows),
        false_alarms=sum(len(m.false_alarms) for m in rows),
        true_silences=sum(len(m.true_silences) for m in rows),
        effect_correct=sum(1 for m in rows if m.effect_call == "correct"),
        effect_wrong=sum(1 for m in rows if m.effect_call == "wrong"),
        effect_unscored=sum(1 for m in rows if m.effect_call == "unscored"),
        unscored_items=sum(len(m.unscored) for m in rows),
    )
