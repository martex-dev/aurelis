"""The closed space an agent may author a strategy out of.

M14 put an agent in the critic's seat, where the closed answer set was a
taxonomy of defects somebody else had written down. This is the other seat, and
it is the one the project exists for: **the agent picks the pieces of a
strategy, and the pieces it picks are the strategy.**

Four properties hold this space shut, and each of them is a defence against a
specific way that "an agent created a strategy" becomes untrue.

**Every choice changes the experiment.** A knob that is hashed into a
specification, charged to the multiple-testing denominator, and justified in an
agent's own words, but which cannot change any number, is decoration — and
decoration in a preregistration is worse than absence, because it makes the
search look wider than it was. :data:`SLOTS` was swept design by design before
it was written down, and one candidate slot failed: ``threshold`` was offered
on the rotation branch and every rotation design returned the same Sharpe for
all three values, because the signal never read it. The engine gained the
parameter rather than the space losing the slot, but the sweep is now a test.

**The agent cannot author its own defect.** There is no slot for costs, none
for the universe, none for the warm-up. Those are exactly the three knobs the
M10 defect taxonomy plants — ``COST_UNDERSTATED``, ``SURVIVORSHIP``,
``LOOKAHEAD`` — and an authoring surface that offered them would let an agent
manufacture a result the company's own critic exists to catch. They come from
the desk, which does not negotiate.

**The space is enumerable, and its size is the thing that gets declared.**
:func:`enumerate_designs` yields every reachable design, exactly, by walking
the branch structure rather than multiplying a guess. That count is what a
preregistration declares as its cells: see :mod:`aurelis.authoring.attempt`.

**Provenance is a decision, but not a design decision.** Which failure a
component answers changes what the company may claim about having created it,
and changes nothing about what runs. So the origin question is asked
separately and is deliberately *not* part of the design space — charging the
false-discovery denominator for a choice that cannot move a number would be as
dishonest in this direction as the inert knob was in the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.agents.decide import Choice, Question
from aurelis.core.canonical import sha256_of
from aurelis.desks.costs import costs_for
from aurelis.engines.spec import (
    BacktestSpec,
    DataSpec,
    ExperimentSpec,
    SignalSpec,
    UniverseSpec,
)
from aurelis.org.desks import Desk
from aurelis.strategy.states import ComponentKind

__all__ = [
    "BASELINES",
    "FAMILY",
    "SLOTS",
    "Design",
    "Slot",
    "baseline_spec",
    "component_spec",
    "enumerate_designs",
    "question_for",
    "render",
    "slots_for",
    "space_size",
]

FAMILY = "family"
"""The first slot, and the one every later slot branches on."""

BASELINES: tuple[str, ...] = ("always_long", "never_trade")
"""What an authored design is measured against, and may not be.

Neither is authorable. A rule that cannot beat holding the asset has not found
anything and a rule that cannot beat doing nothing has found less, so these are
the references — and offering them as choices would let an agent author the
reference and report that it tied.
"""


@dataclass(frozen=True, slots=True)
class Slot:
    """One decision an agent makes, and the complete set of permitted answers.

    ``families`` restricts the slot to signal families it can actually affect.
    An empty set means the slot is always asked. This is the mechanism that
    keeps ``direction`` off the rotation branch: the cross-sectional signal
    never takes a short, so offering the choice there would be a knob with no
    hole behind it.
    """

    name: str
    kind: ComponentKind
    prompt: str
    choices: tuple[Choice, ...]
    families: frozenset[str] = frozenset()

    def applies_to(self, family: str | None) -> bool:
        return not self.families or (family is not None and family in self.families)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(choice.key for choice in self.choices)


SLOTS: tuple[Slot, ...] = (
    Slot(
        name=FAMILY,
        kind=ComponentKind.SIGNAL,
        prompt="What kind of edge is this strategy claiming?",
        choices=(
            Choice(
                "momentum",
                "a name that has risen over the lookback keeps rising",
            ),
            Choice(
                "mean_reversion",
                "a name that has fallen over the lookback comes back",
            ),
            Choice(
                "rotation",
                "rank the whole universe each bar and hold the leaders",
            ),
        ),
    ),
    Slot(
        name="lookback",
        kind=ComponentKind.SIGNAL,
        prompt="How far back does the signal look?",
        choices=(
            # Digits, not words. These were spelled out, and the figure check
            # compares numerals: a model that answered "a 168 bar lookback"
            # was citing the very choice it had been offered and was refused
            # for inventing a figure. The material has to state a number in
            # the form a citation of it will take.
            Choice("six_hours", "6 bars — reacts fast, trades often"),
            Choice("one_day", "24 bars"),
            Choice("three_days", "72 bars"),
            Choice("one_week", "168 bars — slowest"),
        ),
    ),
    Slot(
        name="threshold",
        kind=ComponentKind.ENTRY,
        prompt="How large must the move be before the rule acts on it?",
        choices=(
            Choice("any_move", "act on any move in the right direction"),
            Choice("half_percent", "require a move of 0.005"),
            Choice("two_percent", "require a move of 0.02"),
        ),
    ),
    Slot(
        name="direction",
        kind=ComponentKind.SIZING,
        prompt="May the strategy hold a negative position?",
        choices=(
            Choice("long_only", "hold the name or hold nothing"),
            Choice("long_short", "also take the other side, at twice the turnover"),
        ),
        families=frozenset({"momentum", "mean_reversion"}),
    ),
    Slot(
        name="breadth",
        kind=ComponentKind.SIZING,
        prompt="How many names does the rotation hold at once?",
        choices=(
            Choice("concentrated", "the single leader"),
            Choice("paired", "the top two, equally weighted"),
        ),
        families=frozenset({"rotation"}),
    ),
)

_LOOKBACKS: dict[str, int] = {
    "six_hours": 6,
    "one_day": 24,
    "three_days": 72,
    "one_week": 168,
}
_THRESHOLDS: dict[str, Decimal] = {
    "any_move": Decimal("0"),
    "half_percent": Decimal("0.005"),
    "two_percent": Decimal("0.02"),
}
_BREADTHS: dict[str, int] = {"concentrated": 1, "paired": 2}

_BY_NAME: dict[str, Slot] = {slot.name: slot for slot in SLOTS}


def slots_for(family: str | None) -> tuple[Slot, ...]:
    """The slots asked of an agent that has chosen ``family``.

    ``None`` returns the slots asked before anything has been chosen, which is
    the family slot alone — the branch is not known until it is answered.
    """
    if family is None:
        return (_BY_NAME[FAMILY],)
    return tuple(slot for slot in SLOTS if slot.applies_to(family))


def question_for(slot: Slot) -> Question:
    """The slot as a closed question.

    ``multiple=False`` throughout: a strategy has one lookback. A slot that
    accepted two answers would be describing two strategies, and the
    composition would have to pick — which would put the choice back in the
    software.
    """
    return Question(prompt=slot.prompt, options=slot.choices, multiple=False)


@dataclass(frozen=True, slots=True)
class Design:
    """One reachable point in the space: a slot name against a chosen key."""

    picks: tuple[tuple[str, str], ...]

    @property
    def family(self) -> str:
        return self.get(FAMILY)

    def get(self, name: str) -> str:
        for slot, key in self.picks:
            if slot == name:
                return key
        raise KeyError(f"{name} was not asked of this design")

    def has(self, name: str) -> bool:
        return any(slot == name for slot, _ in self.picks)

    def as_payload(self) -> dict[str, str]:
        return dict(self.picks)

    def digest(self) -> str:
        return sha256_of(self.as_payload())

    def describe(self) -> str:
        return ", ".join(f"{slot}={key}" for slot, key in self.picks)


def enumerate_designs() -> tuple[Design, ...]:
    """Every design an agent could reach, exactly.

    Walked rather than multiplied. The branches have different widths — the two
    single-name families take a direction and the cross-sectional one takes a
    breadth — so a product of slot sizes would be wrong, and wrong in the
    direction that overstates the search.
    """
    designs: list[Design] = []
    for family in _BY_NAME[FAMILY].keys:
        rest = [slot for slot in slots_for(family) if slot.name != FAMILY]
        partials: list[list[tuple[str, str]]] = [[(FAMILY, family)]]
        for slot in rest:
            partials = [
                [*partial, (slot.name, key)] for partial in partials for key in slot.keys
            ]
        designs.extend(Design(tuple(partial)) for partial in partials)
    return tuple(designs)


def space_size() -> int:
    """How many strategies the agent chose between. The declared cells.

    Not one. See :mod:`aurelis.authoring.attempt` for why the company charges
    itself for the space rather than for the pick.
    """
    return len(enumerate_designs())


def render(
    design: Design,
    *,
    desk: Desk | str,
    bars: int,
    interval: str = "1h",
    seed: int = 0,
    source: str = "",
) -> ExperimentSpec:
    """Turn a design into the experiment that measures it.

    Everything the agent chose is in ``signal`` and ``allow_short``. Everything
    the agent may not choose — the desk's costs, a point-in-time universe, the
    warm-up that keeps the priming window untraded — is set here from the desk,
    identically for every design in the space.

    ``source`` names the data, and defaults to the desk's fixture. It is part
    of the specification and therefore part of the digest that gets locked, so
    a registration cannot be honoured by a run against different bars — which
    is what makes a later backtest-against-paper comparison a comparison at
    all rather than a difference between two datasets.
    """
    the_desk = desk if isinstance(desk, Desk) else Desk(desk)
    family = design.family
    lookback = _LOOKBACKS[design.get("lookback")]
    threshold = _THRESHOLDS[design.get("threshold")]
    parameters: dict[str, Any] = {}
    if design.has("breadth"):
        parameters["top_k"] = _BREADTHS[design.get("breadth")]
    allow_short = design.has("direction") and design.get("direction") == "long_short"

    return ExperimentSpec(
        engine="local",
        universe=UniverseSpec(
            desk=the_desk.value,
            symbols=(),
            # Not a choice. A universe chosen with hindsight is the defect the
            # company's own critic is scored on catching, and an authoring
            # surface that offered it would let an agent plant one.
            point_in_time=True,
            selection="point_in_time",
        ),
        data=DataSpec(
            source=source or f"fixture:{the_desk.value}",
            bars=bars,
            interval=interval,
        ),
        signal=SignalSpec(
            kind=family,
            lookback=lookback,
            threshold=threshold,
            parameters=parameters,
        ),
        backtest=BacktestSpec(
            # The desk's own cost model. Also not a choice: understating costs
            # is how a losing rule reads as a winning one, and it is the
            # cheapest defect in the taxonomy to plant.
            costs=costs_for(the_desk).engine_costs(),
            allow_short=allow_short,
            warmup_bars=lookback,
        ),
        seed=seed,
        metrics=(
            "total_return",
            "sharpe",
            "max_drawdown",
            "n_trades",
            "turnover",
            "cost_drag",
        ),
    )


def baseline_spec(
    kind: str,
    *,
    desk: Desk | str,
    bars: int,
    like: ExperimentSpec,
) -> ExperimentSpec:
    """A reference run over exactly the bars the authored design traded.

    ``like`` supplies the warm-up and the costs, so the comparison is between
    two rules on the same window paying the same charges. A baseline measured
    over a longer window would be a different question wearing the same name.
    """
    if kind not in BASELINES:
        raise ValueError(f"{kind} is not a baseline; baselines are {list(BASELINES)}")
    the_desk = desk if isinstance(desk, Desk) else Desk(desk)
    return ExperimentSpec(
        engine="local",
        universe=UniverseSpec(
            desk=the_desk.value,
            symbols=(),
            point_in_time=True,
            selection="point_in_time",
        ),
        data=DataSpec(
            # The reference reads the same bars as the design it references.
            # A baseline measured on the fixture while the design ran on a
            # market would be answering a different question in the same units.
            source=like.data.source,
            bars=bars,
            interval=like.data.interval,
        ),
        signal=SignalSpec(kind=kind, lookback=like.signal.lookback),
        backtest=like.backtest,
        seed=like.seed,
        metrics=like.metrics,
    )


def component_spec(slot: Slot, key: str) -> dict[str, Any]:
    """What the component records about the choice it represents.

    The executable value is carried alongside the key so a reader of the
    component does not have to hold this module in their head to know what
    ``one_week`` meant.
    """
    payload: dict[str, Any] = {"slot": slot.name, "choice": key}
    if slot.name == "lookback":
        payload["bars"] = _LOOKBACKS[key]
    elif slot.name == "threshold":
        payload["move"] = str(_THRESHOLDS[key])
    elif slot.name == "breadth":
        payload["top_k"] = _BREADTHS[key]
    elif slot.name == "direction":
        payload["allow_short"] = key == "long_short"
    elif slot.name == FAMILY:
        payload["signal"] = key
    return payload
