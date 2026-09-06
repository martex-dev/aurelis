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
from enum import StrEnum
from typing import Any

from aurelis.engines.spec import ExperimentSpec
from aurelis.meetings.types import ObjectionSeverity, ObjectionType
from aurelis.org.scopes import ToolScope

__all__ = [
    "LOWER_IS_BETTER",
    "MARKET_DEFECTS",
    "DefectKind",
    "MarketDefect",
    "build_test",
    "defects_for",
]


class DefectKind(StrEnum):
    """What kind of question the mechanical test asks.

    The distinction was forced by M10's truth measurement, which found
    COST_UNDERSTATED "present" in worlds with nothing planted in them at all.
    Of course it was: tripling the cost of a rule that trades makes the rule
    worse whether or not it ever had an edge, so a test read as "did the metric
    get worse" is unfalsifiable.

    ``CORRECTIVE``
        The varied run is the **truer** one. A hindsight universe replaced by a
        point-in-time universe is not a stress test; it is the backtest the
        researcher should have run. Degradation *is* the defect.

    ``STRESS``
        The varied run is a **what-if**. Nobody claims costs really are three
        times higher or that the book really must be wider. So the defect is
        not that the number moved -- it is that **the conclusion did not
        survive**: there was a result, and under the stress there is not one.
        A stress objection against a specification that never showed anything
        settles nothing.
    """

    CORRECTIVE = "corrective"
    STRESS = "stress"


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
    kind: DefectKind
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
    """Re-run on the first half of the window.

    A result that only holds over the whole period, and not over the earlier
    stretch of it, is a statement about one regime rather than about the
    market.

    It is the *first* half because the engine reads bars forward from the
    anchor, so halving ``bars`` truncates the window's end. This docstring
    said "second half" until M10 planted a regime dependency and had to know
    which half the test actually looks at.
    """
    varied = replace(spec, data=replace(spec.data, bars=max(24, spec.data.bars // 2)))
    return {
        "tool": ToolScope.ENGINE_BACKTEST.value,
        "arguments": {"spec": varied.as_payload()},
        "field": metric,
        "comparison": _direction(metric),
        "value": str(observed),
        "describes": "the same rule over the first half of the window",
    }


def _lookahead(spec: ExperimentSpec, metric: str, observed: Decimal) -> dict[str, Any]:
    """Re-run with the first full window of live trading discarded.

    A rule whose result changes sharply when its earliest, half-informed
    positions are excluded was earning something from them. The engine applies
    one-bar latency structurally, so this is a check on the *specification*
    rather than on the loop.

    The warm-up is **twice** the lookback, and that is not a margin of safety.
    At exactly one lookback this test was a provable no-op: every registered
    signal already holds nothing during its own lookback, so suppressing those
    bars suppressed nothing and the varied run was byte-identical to the
    original. It read as a clean bill of health on every specification it was
    ever raised against. M10's truth measurement found it reading exactly zero
    degradation in worlds with a run planted in the priming window, which is
    how a test that could not fail was caught.

    The window is lengthened by one lookback at the same time, and that is the
    only place in this taxonomy where a builder touches two fields. It has to:
    suppressing the extra bars without replacing them would leave the varied
    run trading a *shorter* window, and any rule with a real edge does worse
    over less time. The defect would then be indistinguishable from the
    handicap. Trading bars are held constant at ``bars - lookback`` on both
    sides, so the warm-up is the only thing that differs.
    """
    lookback = max(spec.signal.lookback, 1)
    varied = replace(
        spec,
        data=replace(spec.data, bars=spec.data.bars + lookback),
        backtest=replace(spec.backtest, warmup_bars=lookback * 2),
    )
    return {
        "tool": ToolScope.ENGINE_BACKTEST.value,
        "arguments": {"spec": varied.as_payload()},
        "field": metric,
        "comparison": _direction(metric),
        "value": str(observed),
        "describes": (
            "the same rule with its first full window of live trading discarded"
        ),
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


LOWER_IS_BETTER: frozenset[str] = frozenset(
    {"max_drawdown", "cost_drag", "turnover"}
)
"""Metrics where a *larger* number is worse. Everything else is better larger.

Public, and the single definition of "worse" for anything that reads a
mechanical test: the training suite marks critiques against it and the truth
measurement scores degradation with it. Three private copies of a direction
table is how a deployment that beat its drawdown estimate got recorded as
having fallen short.

It is deliberately **not** the same table as
:data:`aurelis.trading.posttrade.DIRECTIONS`, which calls turnover NEUTRAL.
The two answer different questions. "Did this specification get worse?" has an
answer for turnover -- more of it costs more and caps capacity. "Did paper
turnover beat the backtest's?" does not; it is simply a different number. A
single table that served both would have to be wrong about one of them.
"""


def _direction(metric: str) -> str:
    """The comparison that means "the defect was real".

    An objection predicts the result gets *worse* under the varied run. Which
    way "worse" points depends on the metric, and getting this backwards would
    make every objection unfalsifiable in one direction and automatic in the
    other.
    """
    return "gt" if metric in LOWER_IS_BETTER else "lt"


MARKET_DEFECTS: dict[ObjectionType, MarketDefect] = {
    defect.type: defect
    for defect in (
        MarketDefect(
            ObjectionType.SURVIVORSHIP,
            "Survivorship",
            ObjectionSeverity.CRITICAL,
            DefectKind.CORRECTIVE,
            asks="Was the universe chosen knowing which names survived?",
            varies="the universe, to point-in-time",
            predicts="gets worse once the delisted names are included",
            build=_survivorship,
        ),
        MarketDefect(
            ObjectionType.COST_UNDERSTATED,
            "Understated costs",
            ObjectionSeverity.MAJOR,
            DefectKind.STRESS,
            asks="Does this depend on costs being as low as assumed?",
            varies="the cost model, tripled",
            predicts="gets worse at realistic costs",
            build=_cost_understated,
        ),
        MarketDefect(
            ObjectionType.REGIME_SPECIFIC,
            "Regime specific",
            ObjectionSeverity.MAJOR,
            DefectKind.STRESS,
            asks="Does this hold outside the window it was found in?",
            varies="the window, halved",
            predicts="does not hold over the earlier stretch alone",
            build=_regime_specific,
        ),
        MarketDefect(
            ObjectionType.LOOKAHEAD,
            "Look-ahead",
            ObjectionSeverity.CRITICAL,
            DefectKind.CORRECTIVE,
            asks="Is it earning something from its first, half-informed bars?",
            varies="the start, to one full window after the priming bars",
            predicts="gets worse once the priming window is discarded",
            build=_lookahead,
        ),
        MarketDefect(
            ObjectionType.CAPACITY_IGNORED,
            "Capacity ignored",
            ObjectionSeverity.MAJOR,
            DefectKind.STRESS,
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
