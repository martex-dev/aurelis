"""Market objections, and the mechanical tests that settle them.

An objection in this company is not a worry. It is a claim plus an executable
specification that would settle it — and for the market defects, the
specification is **generated rather than composed**. A Critic selects a defect
type; the builder takes the specification under review and produces the varied
one that would expose it.

That distinction is the point. A critic that writes its own test can write a
test that cannot fail, or one that tests something else, or one that quietly
uses a capability it does not hold. A critic that *names a defect* gets a test
whose construction is written down, reviewed, and identical every time the same
defect is alleged. The prose is the critic's; the arithmetic is not.

Each builder varies exactly one thing, which is what makes the answer
attributable. A test that changed the universe *and* the cost model would
settle nothing, because either could explain the difference.

The taxonomy is closed for the same reason the objection types are: at M10 the
training-scenario suite plants known defects and counts which critics catch
them, and a free-text objection cannot be matched against a planted defect.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from aurelis.engines.spec import ExperimentSpec
from aurelis.meetings.types import ObjectionSeverity, ObjectionType
from aurelis.org.scopes import ToolScope

__all__ = ["MARKET_DEFECTS", "MarketDefect", "build_test", "defects_for"]


@dataclass(frozen=True, slots=True)
class MarketDefect:
    """One way a backtest can be wrong, and how to find out.

    ``predicts`` is the direction the objection asserts. An objection that
    could not be wrong is not an objection, so the builder always produces a
    comparison the varied run might fail to satisfy.
    """

    type: ObjectionType
    name: str
    severity: ObjectionSeverity
    asks: str
    varies: str
    predicts: str
    build: Callable[[ExperimentSpec, str, Decimal], dict[str, Any]]

    def describe(self, metric: str) -> str:
        return f"{self.name}: vary {self.varies}; predict {metric} {self.predicts}"


def _survivorship(spec: ExperimentSpec, metric: str, observed: Decimal) -> dict[str, Any]:
    """Re-run over the universe as it stood, including the names that died.

    The single most consequential defect in a backtest over a survivor list.
    A universe chosen with hindsight cannot lose money on a delisting, because
    the delisted names were never in it -- and ranking rules are drawn towards
    exactly those names, which usually looked like the best ones right up until
    they were not.
    """
    varied = replace(
        spec,
        universe=replace(spec.universe, point_in_time=True, selection="point_in_time"),
    )
    worse = _direction(metric)
    return {
        "tool": ToolScope.ENGINE_BACKTEST.value,
        "arguments": {"spec": varied.as_payload()},
        "field": metric,
        "comparison": worse,
        "value": str(observed),
        "describes": (
            "the same rule over the universe as it actually stood, including "
            "the instruments that later delisted"
        ),
    }


def _cost_understated(
    spec: ExperimentSpec, metric: str, observed: Decimal
) -> dict[str, Any]:
    """Re-run at three times the assumed cost.

    Not a claim that costs *are* three times higher, but a test of whether the
    result depends on them being as low as assumed. A result that survives is
    more robust; one that does not was a cost assumption wearing a signal's
    clothes.
    """
    costs = spec.backtest.costs
    varied = replace(
        spec,
        backtest=replace(
            spec.backtest,
            costs=replace(
                costs,
                fee_bps=costs.fee_bps * 3,
                spread_bps=costs.spread_bps * 3,
                slippage_bps=costs.slippage_bps * 3,
            ),
        ),
    )
    return {
        "tool": ToolScope.ENGINE_BACKTEST.value,
        "arguments": {"spec": varied.as_payload()},
        "field": metric,
        "comparison": _direction(metric),
        "value": str(observed),
        "describes": "the same rule at three times the assumed transaction cost",
    }


def _regime_specific(
    spec: ExperimentSpec, metric: str, observed: Decimal
) -> dict[str, Any]:
    """Re-run on the second half of the window.

    A result that only holds over the whole period, and not over the part of
    it the rule was not tuned on, is a statement about one stretch of history
    rather than about the market.
    """
    varied = replace(spec, data=replace(spec.data, bars=max(24, spec.data.bars // 2)))
    return {
        "tool": ToolScope.ENGINE_BACKTEST.value,
        "arguments": {"spec": varied.as_payload()},
        "field": metric,
        "comparison": _direction(metric),
        "value": str(observed),
        "describes": "the same rule over half the window",
    }


def _lookahead(spec: ExperimentSpec, metric: str, observed: Decimal) -> dict[str, Any]:
    """Re-run with a warm-up that discards the first lookback window.

    A rule whose result changes sharply when its first, partially-informed
    bars are excluded was earning something from them. The engine applies
    one-bar latency structurally, so this is a check on the *specification*
    rather than on the loop.
    """
    varied = replace(
        spec,
        backtest=replace(spec.backtest, warmup_bars=max(spec.signal.lookback, 1)),
    )
    return {
        "tool": ToolScope.ENGINE_BACKTEST.value,
        "arguments": {"spec": varied.as_payload()},
        "field": metric,
        "comparison": _direction(metric),
        "value": str(observed),
        "describes": "the same rule with its first lookback window discarded",
    }


def _capacity_ignored(
    spec: ExperimentSpec, metric: str, observed: Decimal
) -> dict[str, Any]:
    """Re-run holding more names, as size would force.

    A concentrated rule that only works at the very top of its ranking has
    capacity for one position and no more. Widening the book is the cheapest
    proxy for the size a real allocation would carry.
    """
    parameters = dict(spec.signal.parameters)
    parameters["top_k"] = int(parameters.get("top_k", 1)) + 2
    varied = replace(spec, signal=replace(spec.signal, parameters=parameters))
    return {
        "tool": ToolScope.ENGINE_BACKTEST.value,
        "arguments": {"spec": varied.as_payload()},
        "field": metric,
        "comparison": _direction(metric),
        "value": str(observed),
        "describes": "the same rule holding a wider book, as size would force",
    }


#: Metrics where a *larger* number is worse. Everything else is better larger.
_LOWER_IS_BETTER = frozenset({"max_drawdown", "cost_drag", "turnover"})


def _direction(metric: str) -> str:
    """The comparison that means "the defect was real".

    An objection predicts the result gets *worse* under the varied run. Which
    way "worse" points depends on the metric, and getting this backwards would
    make every objection unfalsifiable in one direction and automatic in the
    other.
    """
    return "gt" if metric in _LOWER_IS_BETTER else "lt"


MARKET_DEFECTS: dict[ObjectionType, MarketDefect] = {
    defect.type: defect
    for defect in (
        MarketDefect(
            ObjectionType.SURVIVORSHIP,
            "Survivorship",
            ObjectionSeverity.CRITICAL,
            asks="Was the universe chosen knowing which names survived?",
            varies="the universe, to point-in-time",
            predicts="gets worse once the delisted names are included",
            build=_survivorship,
        ),
        MarketDefect(
            ObjectionType.COST_UNDERSTATED,
            "Understated costs",
            ObjectionSeverity.MAJOR,
            asks="Does this depend on costs being as low as assumed?",
            varies="the cost model, tripled",
            predicts="gets worse at realistic costs",
            build=_cost_understated,
        ),
        MarketDefect(
            ObjectionType.REGIME_SPECIFIC,
            "Regime specific",
            ObjectionSeverity.MAJOR,
            asks="Does this hold outside the window it was found in?",
            varies="the window, halved",
            predicts="does not hold on a different stretch",
            build=_regime_specific,
        ),
        MarketDefect(
            ObjectionType.LOOKAHEAD,
            "Look-ahead",
            ObjectionSeverity.CRITICAL,
            asks="Is it earning something from its first, half-informed bars?",
            varies="the warm-up, to a full lookback",
            predicts="gets worse once the priming window is discarded",
            build=_lookahead,
        ),
        MarketDefect(
            ObjectionType.CAPACITY_IGNORED,
            "Capacity ignored",
            ObjectionSeverity.MAJOR,
            asks="Does this survive being run at size?",
            varies="the book, widened",
            predicts="gets worse in a wider book",
            build=_capacity_ignored,
        ),
    )
}


def defects_for(spec: ExperimentSpec) -> tuple[MarketDefect, ...]:
    """The defects worth alleging against this specification.

    Filtered rather than offered wholesale: capacity means nothing to a rule
    that holds one instrument by construction, and survivorship means nothing
    to one that already ran point-in-time. An objection that cannot apply is
    noise in a review, and noise is what stops real objections being read.
    """
    applicable: list[MarketDefect] = []
    for defect in MARKET_DEFECTS.values():
        if defect.type is ObjectionType.SURVIVORSHIP and spec.universe.point_in_time:
            continue
        if defect.type is ObjectionType.CAPACITY_IGNORED and spec.signal.kind != "rotation":
            continue
        if defect.type is ObjectionType.LOOKAHEAD and spec.backtest.warmup_bars:
            continue
        applicable.append(defect)
    return tuple(applicable)


def build_test(
    defect_type: ObjectionType,
    spec: ExperimentSpec,
    *,
    metric: str,
    observed: Decimal,
) -> dict[str, Any]:
    """The executable test for one alleged defect against one specification."""
    try:
        defect = MARKET_DEFECTS[defect_type]
    except KeyError:
        raise KeyError(
            f"{defect_type} has no mechanical test. Market defects are a closed "
            "taxonomy so that a critic names a defect rather than composing a "
            "test that might not settle anything."
        ) from None
    return defect.build(spec, metric, observed)
