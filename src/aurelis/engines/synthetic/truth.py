"""What is actually in a scenario, measured rather than declared.

The temptation with planted-defect scoring is to write the answer key by hand:
"SC-05 contains survivorship, because I put it there." That answer key is
worthless. A plant can fail to take — a premium can be swamped by noise, a
death can land in a stretch where no rule was holding the name — and grading a
critic against an intention it could not have observed measures nothing but the
author's confidence.

So truth here is a **measurement at a scale no experiment is allowed**
(ADR-0005). A researcher gets one draw of history. This module takes
``replications`` independent draws of the same generating process, runs the
presented specification and every applicable mechanical test on each, and
reports the mean effect and the mean degradation with an interval around it.

Three verdicts, not two:

``PRESENT``   the interval clears the threshold
``ABSENT``    the interval sits below it
``UNDETERMINED``  the interval straddles it

``UNDETERMINED`` items are **excluded from scoring entirely**. A scenario whose
own truth cannot be established is not a fair question, and counting it either
way would put noise into an agent's permanent record.

The two kinds of mechanical test are settled differently, and the first version
of this module got it wrong. A **corrective** test (survivorship, look-ahead)
produces the truer run, so degradation is the defect. A **stress** test (costs,
regime, capacity) produces a what-if, and tripling the cost of a rule that
trades makes it worse whether or not it ever had an edge -- read as degradation,
COST_UNDERSTATED came back "present" in worlds with nothing planted in them at
all. A stress defect is present only when **the conclusion does not survive**:
the presented specification showed an effect, and under the stress it does
not.

:meth:`ScenarioTruth.surprises` names every place the measurement disagreed
with what the catalogue intended. Those are kept and reported, never silently
reconciled: a catalogue that rewrites its intent to match its measurements has
stopped being a check on the generator.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from aurelis.core.canonical import sha256_of
from aurelis.engines.local import LocalEngine
from aurelis.engines.protocol import RunArtifact
from aurelis.engines.spec import ExperimentSpec, spec_from_payload
from aurelis.engines.synthetic.scenarios import CATALOGUE, Scenario
from aurelis.meetings.taxonomy import LOWER_IS_BETTER, DefectKind, build_test, defects_for
from aurelis.meetings.types import ObjectionType

__all__ = [
    "DEFECT_THRESHOLD",
    "EFFECT_THRESHOLD",
    "REPLICATIONS",
    "Bench",
    "Presence",
    "Reading",
    "ScenarioTruth",
    "measure_catalogue",
    "measure_truth",
    "shared_bench",
    "varied_spec",
]

REPLICATIONS = 24
"""Independent draws of each world. No experiment gets more than one.

Twenty-four rather than twelve because twelve was not enough to settle the
borderline readings, and a verdict that flips when the count changes is not a
verdict. Where twenty-four still will not settle one, the answer is
``UNDETERMINED`` and the item goes unscored -- not a larger number chosen until
the reading agreed."""

EFFECT_THRESHOLD = Decimal("0.01")
"""Net total return, after costs, above which an effect is worth the name.
One percent over the window, not per bar."""

DEFECT_THRESHOLD = Decimal("0.01")
"""How far the mechanical test must move the headline metric, in the metric's
own units, before the defect it alleges counts as real."""

_ZERO = Decimal("0")


class Presence(StrEnum):
    """Whether a thing is in the world, as far as measurement can tell."""

    PRESENT = "present"
    ABSENT = "absent"
    UNDETERMINED = "undetermined"
    """Never scored. A question the measurement could not settle is not one an
    agent should be marked wrong on."""


@dataclass(frozen=True, slots=True)
class Reading:
    """A quantity across replications, with the interval that matters."""

    mean: Decimal
    low: Decimal
    high: Decimal
    replications: int
    threshold: Decimal

    @property
    def presence(self) -> Presence:
        if self.low > self.threshold:
            return Presence.PRESENT
        if self.high < self.threshold:
            return Presence.ABSENT
        return Presence.UNDETERMINED

    def as_payload(self) -> dict[str, Any]:
        return {
            "mean": str(self.mean),
            "low": str(self.low),
            "high": str(self.high),
            "replications": self.replications,
            "threshold": str(self.threshold),
            "presence": self.presence.value,
        }

    def describe(self) -> str:
        return f"{self.mean:+.4f} [{self.low:+.4f}, {self.high:+.4f}] over {self.replications}"


def _reading(values: list[Decimal], threshold: Decimal) -> Reading:
    """Mean and a two-standard-error interval, in exact decimal.

    Two standard errors rather than a bootstrap because the replications are
    independent draws by construction — there is no dependence structure to
    preserve, which is the one case where the simple interval is the honest
    one.
    """
    count = len(values)
    if count == 0:
        return Reading(_ZERO, _ZERO, _ZERO, 0, threshold)
    mean = sum(values, _ZERO) / Decimal(count)
    if count < 2:
        return Reading(mean, mean, mean, count, threshold)
    spread = Decimal(str(statistics.pstdev([float(v) for v in values])))
    error = spread * Decimal(2) / Decimal(count).sqrt()
    return Reading(mean, mean - error, mean + error, count, threshold)


@dataclass(frozen=True, slots=True)
class ScenarioTruth:
    """What replication established about one scenario."""

    scenario_id: str
    replications: int
    effect: Reading
    defects: Mapping[ObjectionType, Reading]
    """Degradation under each applicable mechanical test, in metric units."""

    survivals: Mapping[ObjectionType, Reading]
    """For stress tests only: what the varied run *itself* produced.

    This is what decides a stress defect -- whether a result remains after the
    stress, not whether the number moved."""

    intended_effect: bool
    intended_defects: frozenset[ObjectionType]
    scenario_digest: str

    @property
    def effect_present(self) -> Presence:
        return self.effect.presence

    def presence(self, defect: ObjectionType) -> Presence:
        """Whether this defect is really in the scenario.

        Corrective tests are settled by degradation alone. Stress tests are
        settled by survival: the presented run had to show something, and the
        stressed run has to fail to.
        """
        reading = self.defects.get(defect)
        if reading is None:
            return Presence.ABSENT
        survival = self.survivals.get(defect)
        if survival is None:
            return reading.presence
        if self.effect_present is Presence.UNDETERMINED:
            return Presence.UNDETERMINED
        if self.effect_present is Presence.ABSENT:
            # Nothing was claimed, so nothing failed to survive. A stress
            # objection against a specification that never showed a result
            # settles nothing, and scoring it as a catch would reward alleging
            # it everywhere.
            return Presence.ABSENT
        if reading.presence is not Presence.PRESENT:
            return reading.presence
        return {
            Presence.ABSENT: Presence.PRESENT,
            Presence.PRESENT: Presence.ABSENT,
            Presence.UNDETERMINED: Presence.UNDETERMINED,
        }[survival.presence]

    @property
    def real_defects(self) -> frozenset[ObjectionType]:
        """Defects a critic is expected to find."""
        return frozenset(
            d for d in self.defects if self.presence(d) is Presence.PRESENT
        )

    @property
    def absent_defects(self) -> frozenset[ObjectionType]:
        """Defects a critic is penalised for alleging."""
        return frozenset(
            d for d in self.defects if self.presence(d) is Presence.ABSENT
        )

    @property
    def unscored_defects(self) -> frozenset[ObjectionType]:
        return frozenset(
            d for d in self.defects if self.presence(d) is Presence.UNDETERMINED
        )

    @property
    def scorable(self) -> bool:
        """Whether this scenario can be graded at all."""
        return self.effect_present is not Presence.UNDETERMINED or bool(
            self.real_defects | self.absent_defects
        )

    def surprises(self) -> tuple[str, ...]:
        """Where measurement disagreed with what the catalogue intended.

        Reported, not corrected. Each line is a fact about the generator that
        the author got wrong, and it belongs in the open where it can be fixed
        deliberately.
        """
        lines: list[str] = []
        measured = self.effect_present
        if self.intended_effect and measured is not Presence.PRESENT:
            lines.append(
                f"intended a real effect; measured {measured.value} "
                f"({self.effect.describe()})"
            )
        if not self.intended_effect and measured is Presence.PRESENT:
            lines.append(
                f"intended nothing; measured a real effect ({self.effect.describe()})"
            )
        for defect in sorted(self.intended_defects, key=lambda d: d.value):
            found = self.presence(defect)
            if found is not Presence.PRESENT:
                lines.append(
                    f"planted {defect.value}; measured {found.value}"
                    + (
                        f" ({self.defects[defect].describe()})"
                        if defect in self.defects
                        else " (the test does not apply to this specification)"
                    )
                )
        for defect in sorted(self.real_defects, key=lambda d: d.value):
            if defect not in self.intended_defects:
                lines.append(
                    f"did not plant {defect.value}; measured it present "
                    f"({self.defects[defect].describe()})"
                )
        return tuple(lines)

    def as_payload(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_digest": self.scenario_digest,
            "replications": self.replications,
            "effect": self.effect.as_payload(),
            "defects": {
                d.value: {
                    **self.defects[d].as_payload(),
                    "presence": self.presence(d).value,
                    "survives": (
                        self.survivals[d].as_payload() if d in self.survivals else None
                    ),
                }
                for d in sorted(self.defects, key=lambda item: item.value)
            },
            "intended_effect": self.intended_effect,
            "intended_defects": sorted(d.value for d in self.intended_defects),
            "surprises": list(self.surprises()),
        }

    def digest(self) -> str:
        return sha256_of(self.as_payload())


class Bench:
    """Runs scenario specifications, and remembers what they produced.

    Every run here is a pure function of ``(scenario, seed, spec)``, so the
    cache is sound and it is what makes the layer affordable: the truth
    measurement, a playbook's critique and every agent's onboarding all ask for
    the same artifacts, and they are computed once.

    It also means an onboarding cohort of seventeen costs what one costs, which
    is the difference between a suite the company runs and one it talks about.
    """

    __slots__ = ("_runs", "_truth")

    def __init__(self) -> None:
        self._runs: dict[tuple[str, int, str], RunArtifact] = {}
        self._truth: dict[str, ScenarioTruth] = {}

    @property
    def runs(self) -> int:
        """How many distinct engine executions this bench has paid for."""
        return len(self._runs)

    def run(self, scen: Scenario, spec: ExperimentSpec, *, seed: int) -> RunArtifact:
        # Keyed on the scenario *digest*, which covers the world recipe, not on
        # its id. Keying on the id served one world's artifacts for another.
        key = (scen.digest(), seed, spec.digest())
        artifact = self._runs.get(key)
        if artifact is None:
            engine = LocalEngine(scen.world(seed))
            artifact = engine.run(spec)
            self._runs[key] = artifact
        return artifact

    def value(self, scen: Scenario, spec: ExperimentSpec, *, seed: int) -> Decimal:
        """The headline metric of one run."""
        return self.run(scen, spec, seed=seed).metrics.get(scen.metric).value

    def truth(self, scen: Scenario, *, replications: int = REPLICATIONS) -> ScenarioTruth:
        cached = self._truth.get(scen.digest())
        if cached is not None and cached.replications == replications:
            return cached
        measured = measure_truth(scen, bench=self, replications=replications)
        self._truth[scen.digest()] = measured
        return measured


def measure_truth(
    scen: Scenario,
    *,
    bench: Bench | None = None,
    replications: int = REPLICATIONS,
) -> ScenarioTruth:
    """Establish what is in a scenario by replicating it.

    Seeds ``1..replications``. Seed ``0`` is reserved for the single draw a
    critic is shown, and is deliberately not one of the draws that settles the
    answer — otherwise the question would contain its own answer.
    """
    bench = bench or Bench()
    presented = scen.presented()
    seeds = range(1, replications + 1)

    baselines = {seed: bench.value(scen, presented, seed=seed) for seed in seeds}
    effect = _reading([baselines[seed] for seed in seeds], EFFECT_THRESHOLD)

    defects: dict[ObjectionType, Reading] = {}
    stressed: dict[ObjectionType, Reading] = {}
    worse_is_larger = scen.metric in LOWER_IS_BETTER
    for defect in defects_for(presented):
        test = build_test(
            defect.type, presented, metric=scen.metric, observed=baselines[1]
        )
        varied = spec_from_payload(test["arguments"]["spec"])
        under_test = {seed: bench.value(scen, varied, seed=seed) for seed in seeds}
        degradations = [
            (under_test[seed] - baselines[seed])
            if worse_is_larger
            else (baselines[seed] - under_test[seed])
            for seed in seeds
        ]
        defects[defect.type] = _reading(degradations, DEFECT_THRESHOLD)
        if defect.kind is DefectKind.STRESS:
            stressed[defect.type] = _reading(
                [under_test[seed] for seed in seeds], EFFECT_THRESHOLD
            )

    return ScenarioTruth(
        scenario_id=scen.scenario_id,
        replications=replications,
        effect=effect,
        defects=defects,
        survivals=stressed,
        intended_effect=scen.intended_effect,
        intended_defects=scen.intended_defects,
        scenario_digest=scen.digest(),
    )


def varied_spec(scen: Scenario, defect: ObjectionType, observed: Decimal) -> ExperimentSpec:
    """The specification one mechanical test would run.

    Built through :func:`aurelis.meetings.taxonomy.build_test`, the same
    function a Chair uses to settle an objection in a live meeting. A training
    suite that constructed its own variations would be scoring critics against
    tests the company does not actually run.
    """
    presented = scen.presented()
    test = build_test(defect, presented, metric=scen.metric, observed=observed)
    return spec_from_payload(test["arguments"]["spec"])


_SHARED: Bench | None = None


def shared_bench() -> Bench:
    """The process-wide bench.

    Every run it holds is a pure function of ``(scenario, seed, spec)``, so
    sharing it across runtimes, suites and test cases changes no answer -- and
    without it the truth measurement is paid again for every ``Runtime`` built,
    which is roughly twenty seconds each and would make the test suite
    unrunnable. Correctness does not depend on this; affordability does.
    """
    global _SHARED
    if _SHARED is None:
        _SHARED = Bench()
    return _SHARED


def measure_catalogue(
    *, bench: Bench | None = None, replications: int = REPLICATIONS
) -> tuple[ScenarioTruth, ...]:
    """Replicate every scenario. The suite's answer key, computed."""
    bench = bench or shared_bench()
    return tuple(bench.truth(s, replications=replications) for s in CATALOGUE)
