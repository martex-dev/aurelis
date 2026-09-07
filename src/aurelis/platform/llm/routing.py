"""Which model answers, decided by the charter rather than by the call site.

Every charter in the registry declares a :class:`~aurelis.core.enums.ModelTier`,
and :func:`~aurelis.org.registry.resolve_authority` has always computed an
agent's tier as the highest among the charters it covers. Until M17 that number
was computed and then thrown away: every call site in the company passed the
literal string ``"mock-1"``, so the tier system was a declaration with nothing
downstream of it. Point the runtime at a real provider and it would have asked
Anthropic for a model called ``mock-1``.

This module is the missing half. It maps *(provider, tier)* to a model id, and
three properties make it worth being a module rather than a dictionary.

**Routing is per provider, not global.** The mock provider answers every tier
with ``mock-1``, and it must, or the entire offline test suite would start
naming models nobody can call. A route table keyed only by tier would have to
special-case the mock somewhere else.

**``NONE`` is refused, loudly.** ``ModelTier.NONE`` is a real tier covering
seven charters and most of the company's routine work — every deterministic
officer, every statistic, every scheduled check. Asking this module for a model
at that tier means a code path is about to spend money on arithmetic, so it
raises rather than quietly returning the cheap model. A silent fallback there
would make the cheapest possible bug — a model call that should have been a
function call — the hardest one to notice.

**Every routed model must be priced.** A model id with no row in
:mod:`aurelis.platform.llm.pricing` cannot be budgeted against, and an unpriced
call is one that looks free. The table is checked against the price table at
import, so a typo is an ``ImportError`` at startup rather than a zero in the
cost ledger.

What this makes visible
-----------------------

An agent's tier is the **highest** of the charters it holds, because it has to
be capable of its most demanding role. At the launch roster that has a price:
six of the seventeen agents hold at least one ``HIGH`` charter, so *all* their
work routes to the most expensive model — including the ``LOW``-tier charters
they also hold. AUDIT covers six charters spanning low, mid and high, and its
cheapest work bills at fifteen times the rate that work needs.

That is not an argument against generalists; it is a measurable cost of them,
and the company already has the machinery to act on it. Fission (M11) moves a
charter to its own agent, and after a split the low-tier work routes low.
``aurelis model tiers`` prints the whole picture.
"""

from __future__ import annotations

from aurelis.core.enums import ModelTier
from aurelis.core.errors import ConfigurationError
from aurelis.platform.llm.pricing import PRICES

__all__ = [
    "MOCK_MODEL",
    "NoModelForTier",
    "model_for",
    "routed_models",
    "routes_for",
    "unpriced_routes",
]

MOCK_MODEL = "mock-1"
"""What the offline provider answers with, at every tier.

Not a placeholder. It is priced at zero explicitly so an offline run produces a
real cost row of zero rather than no row at all, and routing it uniformly is
what keeps the whole suite offline while the tier machinery is exercised.
"""

_REAL: dict[ModelTier, str] = {
    ModelTier.LOW: "claude-haiku-4-5-20251001",
    ModelTier.MID: "claude-sonnet-5",
    ModelTier.HIGH: "claude-opus-5",
}
"""The tier ladder for any provider that reaches a real model.

Shared by the subscription and the metered API on purpose: the same role should
get the same model whichever way the company is paying for it, or a cost
experiment would be measuring the payment method rather than the work.
"""

ROUTES: dict[str, dict[ModelTier, str]] = {
    "mock": dict.fromkeys(_REAL, MOCK_MODEL),
    "agent_sdk": dict(_REAL),
    "anthropic_api": dict(_REAL),
}


class NoModelForTier(ConfigurationError):
    """The provider has no model for this tier, or the tier asks for none."""


def model_for(provider: str, tier: ModelTier) -> str:
    """The model id this provider uses for work at this tier.

    Raises :class:`NoModelForTier` for ``ModelTier.NONE`` — that tier means the
    work is deterministic and no model should be called at all, so reaching
    here with it is a bug in the caller rather than a configuration gap.
    """
    if tier is ModelTier.NONE:
        raise NoModelForTier(
            "ModelTier.NONE means the work is deterministic and no model is "
            "called. Routing it to the cheapest model would turn a function "
            "call that should exist into a bill nobody notices."
        )
    try:
        table = ROUTES[provider]
    except KeyError:
        raise NoModelForTier(
            f"no routing table for provider {provider!r}; known providers are "
            f"{', '.join(sorted(ROUTES))}. A provider with no table cannot be "
            "asked for a model without inventing one."
        ) from None
    try:
        return table[tier]
    except KeyError:
        raise NoModelForTier(
            f"provider {provider!r} has no model for tier {tier.value!r}. "
            "Add one to ROUTES rather than falling back: a role routed to the "
            "wrong tier is a silent change to what the company can think with."
        ) from None


def routes_for(provider: str) -> dict[ModelTier, str]:
    """The whole ladder for one provider, cheapest first."""
    try:
        table = ROUTES[provider]
    except KeyError:
        raise NoModelForTier(
            f"no routing table for provider {provider!r}"
        ) from None
    order = (ModelTier.LOW, ModelTier.MID, ModelTier.HIGH)
    return {tier: table[tier] for tier in order if tier in table}


def routed_models() -> frozenset[str]:
    """Every model id any provider can route to."""
    return frozenset(model for table in ROUTES.values() for model in table.values())


def unpriced_routes() -> tuple[str, ...]:
    """Routed models with no price. Empty, or the company cannot budget."""
    return tuple(sorted(model for model in routed_models() if model not in PRICES))


_MISSING = unpriced_routes()
if _MISSING:  # pragma: no cover - a typo here fails at import, which is the point
    raise ConfigurationError(
        f"routed models have no price: {', '.join(_MISSING)}. An unpriced model "
        "cannot be budgeted against, and a call that looks free is the one that "
        "runs away. Add it to aurelis.platform.llm.pricing.PRICES."
    )
