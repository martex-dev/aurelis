"""Strategies: composed from authored components, never promoted from a result.

The distinction this package exists to enforce is between *finding* an edge and
*creating* one. There is no function anywhere here that turns a hypothesis into
a strategy — no ``promote_hypothesis``, no foreign key from a version to a
result. A company that could promote its best measurement would be a selection
engine, producing only what its corpus already contained and stopping the day
the corpus ran out.

What exists instead: agents author :class:`~aurelis.strategy.tables.Component`
pieces with stated reasoning and a cited :class:`~aurelis.strategy.states.Origin`,
and a version is what those pieces make. Failed research is material for that —
``DERIVED_FROM_FAILURE`` is a component answering a specific refutation, citing
it — which is what a graveyard is actually for.

:meth:`~aurelis.strategy.synthesis.Synthesis.novelty` then measures how much of
a composition the company wrote versus inherited, so "did we create this?" is a
count of origins rather than a claim.

The second thing this package refuses to assume is that a market is a market.
The inherited corpus was measured on crypto alone and Aurelis covers seven
desks, so every version's behaviour off its native desk is ``UNPROVEN`` until
measured there, and a component whose structural assumptions a desk cannot meet
is ``INAPPLICABLE`` rather than merely untested.
"""

from aurelis.strategy.gates import GATE_OWNERS, GateOutcome, GateReport, Gates
from aurelis.strategy.lifecycle import PromotionRefused, Strategies
from aurelis.strategy.markets import Assumption, MarketProfile, profile
from aurelis.strategy.states import (
    ComponentKind,
    Gate,
    Origin,
    Portability,
    PortfolioMode,
    RiskDecision,
    StrategyState,
    may_transition,
)
from aurelis.strategy.synthesis import Composition, Novelty, Synthesis
from aurelis.strategy.tables import (
    Component,
    PromotionGate,
    Strategy,
    StrategyLineage,
    StrategyPortability,
    StrategyVersion,
    VersionComponent,
)
from aurelis.strategy.triggers import (
    expected_strategy_trigger_names,
    install_strategy_invariants,
    verify_strategy_invariants,
)

__all__ = [
    "GATE_OWNERS",
    "Assumption",
    "Component",
    "ComponentKind",
    "Composition",
    "Gate",
    "GateOutcome",
    "GateReport",
    "Gates",
    "MarketProfile",
    "Novelty",
    "Origin",
    "Portability",
    "PortfolioMode",
    "PromotionGate",
    "PromotionRefused",
    "RiskDecision",
    "Strategies",
    "Strategy",
    "StrategyLineage",
    "StrategyPortability",
    "StrategyState",
    "StrategyVersion",
    "Synthesis",
    "VersionComponent",
    "expected_strategy_trigger_names",
    "install_strategy_invariants",
    "may_transition",
    "profile",
    "verify_strategy_invariants",
]
