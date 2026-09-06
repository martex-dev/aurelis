"""The strategy vocabulary.

Three distinctions here carry the weight of the milestone.

**A strategy is built, not promoted.** There is no transition from "the best
hypothesis" to "a strategy". A strategy is *composed* from components that
agents authored, and :class:`Origin` records where each one came from — which
meeting invented it, which failure it answers, which inherited trial it was
adapted from. The company's purpose is to *create* an edge, not to sift a
corpus for one, and a vocabulary that let a hypothesis become a strategy by
being promoted would quietly make it a selection engine.

**Where a strategy works is a claim, not a property.** The corpus Aurelis
inherited was tested on crypto alone; the company covers seven markets. So a
version is built *on* one desk and its behaviour anywhere else is
:class:`Portability.UNPROVEN` until measured there. Assuming portability is how
one market's regularity becomes seven markets' false discovery.

**Backward transitions are normal.** ``DEGRADED`` and ``SUSPENDED`` are
ordinary destinations reached by preregistered rules, not failures of process.
A lifecycle that only moved forward would be describing a sales funnel.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ComponentKind",
    "Gate",
    "MATERIAL_FIELDS",
    "Origin",
    "PortfolioMode",
    "Portability",
    "RiskDecision",
    "STRATEGY_TRANSITIONS",
    "StrategyState",
    "may_transition",
]


class ComponentKind(StrEnum):
    """What part of a strategy a component is.

    A closed set, and deliberately small. These are the pieces an agent can
    author and recombine; a strategy is exactly a composition of them plus a
    universe and a cost model.
    """

    SIGNAL = "signal"
    """Produces a number per instrument per bar. The idea itself."""

    FILTER = "filter"
    """Removes instruments or bars from consideration. A regime gate, a
    liquidity floor."""

    ENTRY = "entry"
    EXIT = "exit"
    SIZING = "sizing"
    """How much. Separate from the signal, because conflating them is how a
    weak edge gets rescued by leverage and nobody notices."""


class Origin(StrEnum):
    """Where a component came from. Required — there is no default.

    This is the field that answers the question the whole project turns on:
    *did the company create this, or did it find it?* An origin of
    ``ADAPTED`` with a corpus citation is an honest inheritance; the same
    component claiming ``INVENTED`` would be the company taking credit for
    somebody else's work, and would make its own novelty unmeasurable.
    """

    INVENTED = "invented"
    """Authored here, from reasoning rather than from an existing component.
    Must cite the meeting or task where the invention happened."""

    DERIVED_FROM_FAILURE = "derived_from_failure"
    """Answers a specific refuted hypothesis. Must cite it. The most valuable
    origin in the taxonomy: it is what a graveyard is *for*."""

    ADAPTED = "adapted"
    """Taken from inherited prior art and changed. Must cite the corpus trial
    or hypothesis it came from."""

    REFINED = "refined"
    """A parameter or rule change to an existing component. Must cite the
    parent component."""

    COMBINED = "combined"
    """Built by composing existing components. Must cite them."""


class Portability(StrEnum):
    """What is known about a version on a desk other than the one it was built
    for."""

    NATIVE = "native"
    """The desk it was authored and measured on."""

    UNPROVEN = "unproven"
    """Not measured here. The default everywhere else, and never treated as
    working."""

    PORTED = "ported"
    """Measured on this desk and it held."""

    REFUTED_HERE = "refuted_here"
    """Measured on this desk and it did not hold. Kept, because "works on
    crypto, fails on equities" is a finding about the idea."""

    INAPPLICABLE = "inapplicable"
    """A structural assumption does not hold here — a 24/7 funding signal on a
    calendar market. Declared, not discovered by a confusing result."""


class StrategyState(StrEnum):
    IDEA = "idea"
    CANDIDATE = "candidate"
    RESEARCHING = "researching"
    PROMISING = "promising"
    UNDER_REVIEW = "under_review"
    VALIDATED = "validated"
    PAPER_TRADING = "paper_trading"
    MONITORING = "monitoring"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"
    REJECTED = "rejected"
    RETIRED = "retired"


STRATEGY_TRANSITIONS: dict[StrategyState, frozenset[StrategyState]] = {
    StrategyState.IDEA: frozenset({StrategyState.CANDIDATE, StrategyState.REJECTED}),
    StrategyState.CANDIDATE: frozenset(
        {StrategyState.RESEARCHING, StrategyState.REJECTED}
    ),
    StrategyState.RESEARCHING: frozenset(
        {StrategyState.PROMISING, StrategyState.REJECTED}
    ),
    StrategyState.PROMISING: frozenset(
        {StrategyState.UNDER_REVIEW, StrategyState.REJECTED}
    ),
    StrategyState.UNDER_REVIEW: frozenset(
        {StrategyState.VALIDATED, StrategyState.REJECTED, StrategyState.PROMISING}
    ),
    StrategyState.VALIDATED: frozenset(
        {StrategyState.PAPER_TRADING, StrategyState.SUSPENDED, StrategyState.RETIRED}
    ),
    StrategyState.PAPER_TRADING: frozenset(
        {StrategyState.MONITORING, StrategyState.SUSPENDED, StrategyState.DEGRADED}
    ),
    StrategyState.MONITORING: frozenset(
        {StrategyState.DEGRADED, StrategyState.SUSPENDED, StrategyState.RETIRED}
    ),
    StrategyState.DEGRADED: frozenset(
        {StrategyState.MONITORING, StrategyState.SUSPENDED, StrategyState.RETIRED}
    ),
    StrategyState.SUSPENDED: frozenset(
        {StrategyState.MONITORING, StrategyState.RETIRED}
    ),
    StrategyState.REJECTED: frozenset({StrategyState.RETIRED}),
}


def may_transition(current: str, target: str) -> bool:
    try:
        return StrategyState(target) in STRATEGY_TRANSITIONS[StrategyState(current)]
    except (ValueError, KeyError):
        return False


class Gate(StrEnum):
    """The promotion gates, registered before evaluation.

    Registered first so success criteria cannot be chosen after seeing
    results — the same rule as a preregistration, applied to deployment.
    """

    A_STATISTICAL = "A"
    """Deflated Sharpe against the **lifetime** trial count, not the family's."""

    B_BENCHMARK = "B"
    """Beats the desk's naive benchmark on the same instruments, window and
    costs. A strategy that loses to buy-and-hold is not a strategy."""

    C_INDEPENDENCE = "C"
    """Correlation with every deployed strategy below a registered bound. The
    best individual strategy is not automatically a portfolio component."""

    D_INTEGRITY = "D"
    """No open critical objections; point-in-time universe; realistic costs."""

    E_REPLICATION = "E"
    """At least one surviving replication with a declared variation."""

    F_CUSTODY = "F"
    """At most one sealed-window query, and it passed."""

    G_CAPACITY = "G"
    """Capacity at or above the intended allocation, at realistic
    participation."""


MATERIAL_FIELDS = frozenset(
    {"universe", "components", "cost_model", "sizing", "constraints"}
)
"""What makes a change material.

A material change to a ``VALIDATED`` version creates a new version at
``UNDER_REVIEW`` and triggers revalidation. Anything here changes what the
strategy *does*; a name or a note does not.
"""


class PortfolioMode(StrEnum):
    """How a portfolio's numbers were produced.

    **There is no LIVE member.** Adding one is a schema migration and a review,
    not a configuration change — ADR-0006. A mode enum with a live value and a
    disabled flag is one flag away from real money.
    """

    BACKTEST = "backtest"
    SIMULATION = "simulation"
    PAPER = "paper"


class RiskDecision(StrEnum):
    """What Risk did. Recorded even when it changed nothing.

    ``ALLOW`` exists so that "Risk permitted this" and "Risk was never
    consulted" are different rows rather than the same silence.
    """

    ALLOW = "allow"
    SHRINK = "shrink"
    VETO = "veto"
    HALT = "halt"
    """Stops execution on a desk or company-wide, not just this proposal."""
