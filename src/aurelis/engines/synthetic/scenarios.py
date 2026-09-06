"""The scenario catalogue: worlds with a known answer, and the spec shown.

A scenario pairs a :class:`~aurelis.engines.synthetic.world.WorldRecipe` with
the **presented specification** — the experiment a critic is handed, defect and
all. The recipe plants; the presentation is what a careless researcher would
have written.

``intended_effect`` and ``intended_defects`` record what the author was
*aiming* for. They are not the answer key. A premium can be swamped by noise, a
death can land where no rule was holding it, and a plant that did not take must
not be scored as though it had. What the suite actually grades against is
measured in :mod:`aurelis.engines.synthetic.truth`, and
:meth:`ScenarioTruth.surprises` reports every place the measurement disagreed
with the intent — kept and shown rather than quietly reconciled, because a
catalogue that edits its intent to match its measurements has stopped being a
check on anything.

The catalogue is deliberately a third nothing. A system that always finds
something must score badly, and it can only do that if there is something to
score badly on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from aurelis.core.canonical import sha256_of
from aurelis.engines.local import SYNTHETIC_DESK
from aurelis.engines.spec import (
    BacktestSpec,
    CostModel,
    DataSpec,
    ExperimentSpec,
    SignalSpec,
    UniverseSpec,
)
from aurelis.engines.synthetic.world import Death, SyntheticWorld, WorldRecipe
from aurelis.meetings.types import ObjectionType

__all__ = ["CATALOGUE", "Scenario", "catalogue_digest", "scenario"]

_ZERO = Decimal("0")

_THIN_COSTS = CostModel(
    fee_bps=Decimal("3"), spread_bps=Decimal("2"), slippage_bps=Decimal("1")
)
"""Optimistic costs. Not wrong on their face — a thin edge that only survives
them is what COST_UNDERSTATED is for."""


@dataclass(frozen=True, slots=True)
class Scenario:
    """One world, one specification, and what was planted in it."""

    scenario_id: str
    title: str
    recipe: WorldRecipe
    signal: SignalSpec
    intended_effect: bool
    intended_defects: frozenset[ObjectionType] = frozenset()
    metric: str = "total_return"
    point_in_time: bool = True
    """The **presented** universe basis. ``False`` is the survivorship defect:
    the spec quietly asks for the names that are still trading."""

    costs: CostModel = field(default_factory=CostModel)
    note: str = ""

    def world(self, seed: int) -> SyntheticWorld:
        """One draw of this scenario's generating process.

        An experiment gets one of these. The truth measurement gets many, and
        that asymmetry is the whole reason a score means anything.
        """
        return SyntheticWorld(self.recipe, seed)

    def presented(self) -> ExperimentSpec:
        """The specification as a critic receives it."""
        return ExperimentSpec(
            engine="local",
            universe=UniverseSpec(
                desk=SYNTHETIC_DESK,
                symbols=(),
                point_in_time=self.point_in_time,
                selection="point_in_time" if self.point_in_time else "survivors_only",
            ),
            data=DataSpec(source=f"scenario:{self.scenario_id}", bars=self.recipe.bars),
            signal=self.signal,
            backtest=BacktestSpec(costs=self.costs),
            metrics=("total_return", "sharpe", "max_drawdown", "n_trades", "turnover"),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "spec": self.presented().as_payload(),
            "world": self.recipe.as_payload(),
            "intended_effect": self.intended_effect,
            "intended_defects": sorted(d.value for d in self.intended_defects),
            "metric": self.metric,
        }

    def digest(self) -> str:
        """The scenario's identity: the world *and* the specification shown.

        The world has to be in it. Without the recipe, two scenarios that
        present the same specification over different plants hash identically
        -- and a run cache keyed on that digest would serve one scenario's
        artifacts for the other. That is not hypothetical: it happened while
        this catalogue was being tuned, and every candidate world in a sweep
        came back with byte-identical numbers.
        """
        return sha256_of(self.as_payload())


def _momentum(lookback: int = 6) -> SignalSpec:
    return SignalSpec(kind="momentum", lookback=lookback, threshold=_ZERO)


def _rotation(lookback: int = 6, top_k: int = 1) -> SignalSpec:
    return SignalSpec(kind="rotation", lookback=lookback, parameters={"top_k": top_k})


_QUIET = WorldRecipe(volatility=Decimal("0.02"))
_LOUD = WorldRecipe(volatility=Decimal("0.05"))


CATALOGUE: tuple[Scenario, ...] = (
    # ------------------------------------------------------------ nothing
    Scenario(
        "SC-01",
        "A random walk, and a momentum rule that wants it to be more",
        _QUIET,
        _momentum(),
        intended_effect=False,
        note=(
            "Nothing is planted. The rule trades, pays costs, and should end "
            "up behind. A critic that finds a defect here has invented one."
        ),
    ),
    Scenario(
        "SC-02",
        "A random walk, ranked",
        _QUIET,
        _rotation(),
        intended_effect=False,
        note="The same emptiness, cross-sectionally. Rotation finds leaders in noise.",
    ),
    Scenario(
        "SC-03",
        "Loud noise, which looks like signal",
        _LOUD,
        _momentum(lookback=12),
        intended_effect=False,
        note=(
            "Volatility without structure. Its effect is UNDETERMINED at "
            "every replication count tried, and that is the entry: some "
            "questions do not have an answer at any sample size a company "
            "can afford, and the suite has to be able to say so instead of "
            "grading a coin toss."
        ),
    ),
    # ------------------------------------------------- a real, clean effect
    Scenario(
        "SC-04",
        "A genuine momentum premium, honestly specified",
        WorldRecipe(premium=Decimal("0.15"), premium_lookback=6),
        _momentum(),
        intended_effect=True,
        note=(
            "Point-in-time universe, realistic costs, effect present "
            "throughout. Everything a critic could allege here is false."
        ),
    ),
    # -------------------------------------------------------- survivorship
    Scenario(
        "SC-05",
        "The names that died are missing from the list",
        _QUIET.with_deaths(Death("ZZA", 52), Death("ZZB", 68)),
        _rotation(),
        intended_effect=False,
        intended_defects=frozenset({ObjectionType.SURVIVORSHIP}),
        point_in_time=False,
        note=(
            "The casualties drift up before they go. A ranking rule run over "
            "the survivors never has to hold one through the mark-down."
        ),
    ),
    Scenario(
        "SC-06",
        "The same, in a wider book",
        _QUIET.with_deaths(Death("ZZA", 44), Death("ZZB", 60), Death("ZZC", 76)),
        _rotation(top_k=2),
        intended_effect=False,
        intended_defects=frozenset({ObjectionType.SURVIVORSHIP}),
        point_in_time=False,
        note="Three casualties and two slots, so the bias has more room to work.",
    ),
    # ---------------------------------------------------------------- cost
    Scenario(
        "SC-07",
        "An edge the width of the spread",
        WorldRecipe(premium=Decimal("0.12"), premium_lookback=3),
        _rotation(lookback=3),
        intended_effect=True,
        intended_defects=frozenset({ObjectionType.COST_UNDERSTATED}),
        costs=_THIN_COSTS,
        note=(
            "Real, and real only at the assumed cost. A three-bar ranking "
            "rule changes its mind constantly, so tripling the cost model is "
            "what settles whether this was a signal or an accounting "
            "assumption. Measured: the edge is there at the assumed cost and "
            "gone at three times it."
        ),
    ),
    # -------------------------------------------------------------- regime
    Scenario(
        "SC-08",
        "An effect that only exists in the back half",
        WorldRecipe(premium=Decimal("0.22"), premium_lookback=6, regime_from=48),
        _momentum(),
        intended_effect=True,
        intended_defects=frozenset({ObjectionType.REGIME_SPECIFIC}),
        note=(
            "The full window shows an edge. The earlier half of it shows "
            "nothing, because there was nothing there to find."
        ),
    ),
    # ------------------------------------------------------------ priming
    Scenario(
        "SC-09",
        "Earnings from the half-informed bars",
        WorldRecipe(priming=Decimal("0.035"), priming_bars=14),
        _momentum(lookback=6),
        intended_effect=True,
        intended_defects=frozenset({ObjectionType.LOOKAHEAD}),
        note=(
            "A run inside the first lookback window. The engine's one-bar "
            "latency is intact -- what is planted is a specification that "
            "starts trading before its indicator has settled."
        ),
    ),
    # ----------------------------------------------------------- capacity
    Scenario(
        "SC-10",
        "An edge that fits in one position",
        WorldRecipe(
            premium=Decimal("0.22"), premium_lookback=6, dispersion=Decimal("3")
        ),
        _rotation(top_k=1),
        intended_effect=True,
        intended_defects=frozenset({ObjectionType.CAPACITY_IGNORED}),
        note=(
            "Only the leading name carries the premium; the rest carry a "
            "tilt against it, so a wider book is not dilution but damage. "
            "THE PLANT DID NOT TAKE. Measurement says the effect survives "
            "being widened, and it says so at every replication count tried "
            "-- the leader keeps enough of the premium at a third of the "
            "weight. Settings that did report the defect flipped their answer "
            "between 24 and 40 replications, which is not a verdict. So this "
            "scenario is scored on its effect and its absent defects only, "
            "CAPACITY_IGNORED currently has no scorable scenario anywhere in "
            "the suite, and the disagreement is reported by "
            "ScenarioTruth.surprises rather than tuned away."
        ),
    ),
    # ------------------------------------------------------- two at once
    Scenario(
        "SC-11",
        "A thin edge on a survivor list",
        WorldRecipe(premium=Decimal("0.12"), premium_lookback=3).with_deaths(
            Death("ZZA", 48), Death("ZZB", 64)
        ),
        _rotation(lookback=3, top_k=1),
        intended_effect=True,
        intended_defects=frozenset(
            {ObjectionType.SURVIVORSHIP, ObjectionType.COST_UNDERSTATED}
        ),
        costs=_THIN_COSTS,
        point_in_time=False,
        note=(
            "SC-07's world with two casualties added and a survivor-only "
            "list to hide them. Two defects in one specification, and a "
            "critic that stops at the first one it finds scores a miss on "
            "the second."
        ),
    ),
    Scenario(
        "SC-12",
        "Real, and only lately",
        WorldRecipe(premium=Decimal("0.24"), premium_lookback=6, regime_from=56),
        _rotation(top_k=1),
        intended_effect=True,
        intended_defects=frozenset({ObjectionType.REGIME_SPECIFIC}),
        note=(
            "The hard case. The effect is genuinely there and the objection "
            "is genuinely right, and a critic has to say both."
        ),
    ),
)
"""Twelve scenarios: three with nothing planted, one clean effect, and eight
carrying at least one defect from the closed taxonomy."""


_BY_ID = {s.scenario_id: s for s in CATALOGUE}


def scenario(scenario_id: str) -> Scenario:
    try:
        return _BY_ID[scenario_id]
    except KeyError:
        raise KeyError(
            f"no scenario {scenario_id!r}; the catalogue holds {sorted(_BY_ID)}"
        ) from None


def catalogue_digest() -> str:
    """One hash over every scenario.

    A training record cites it, so a score can never be compared against one
    earned on a different set of worlds.
    """
    return sha256_of([s.as_payload() for s in CATALOGUE])
