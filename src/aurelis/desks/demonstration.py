"""M12's demonstration: the same question, asked on all seven desks.

.. code-block:: text

    for each desk:
        open it            checklist evaluated; caveats carried
        propose            the same claim, worded for the desk
        screen             against prior art from the other desks
        preregister        locked, hashed, with the desk's own cost model
        design + run       the desk's fixture, on the desk's calendar
        conclude           a verdict from the pure rule

    then: put the seven results side by side, annualised

The comparison is the point, and it is the part that did not work before. The
engine reports Sharpe as ``per_bar``; crypto samples 8760 bars a year and
equities 252, so the same per-bar number means something 5.9 times larger on
crypto. Ranking the seven raw would rank them by sampling frequency. Every
figure in the final table is converted through its own desk's calendar, and the
conversion factor is printed beside it.

What this does **not** show is seven markets being researched. It shows seven
desks' machinery — clocks, cost models, liquidity ceilings, risk limits,
universes with their own casualties — driving the same research lifecycle to a
verdict, over fixture data with no feed behind any of it. Every artifact says
so, and so does every line of the report.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.desks.calendars import calendar_for
from aurelis.desks.comparability import Comparable, Incomparable, annualise
from aurelis.desks.costs import costs_for
from aurelis.desks.power import PowerRequirement, bars_for_span, required_observations
from aurelis.engines.spec import (
    BacktestSpec,
    DataSpec,
    ExperimentSpec,
    SignalSpec,
    UniverseSpec,
)
from aurelis.org.desks import DESKS, Desk
from aurelis.research.states import Verdict
from aurelis.runtime import Runtime

__all__ = ["DeskResult", "MultiDeskOutcome", "run_multi_desk"]

#: The claim, asked identically everywhere. A momentum rule is the one signal
#: every desk can express, which is what makes the seven answers comparable at
#: all -- a different rule per desk would confound the desk with the question.
_LOOKBACK = 12
_INTERVAL = "1h"

CLAIM = Decimal("1.0")
"""The claim, stated **annualised**.

Per-bar would be seven different questions wearing one number: a per-bar Sharpe
of 0.05 is an annualised 4.7 on crypto and 2.0 on equities. Annualised, the
same words mean the same thing everywhere, and each desk's per-bar minimum
effect is derived from it through that desk's own calendar.
"""

SPAN_YEARS = Decimal("0.25")
"""The research budget, stated in **time** rather than in bars.

One quarter on every desk, which is 2190 hourly bars on crypto and 409 on the
NYSE. A budget in bars would give crypto seven weeks and equities nine months
for the same number, and would systematically underpower whichever desk sampled
fastest while looking scrupulously even-handed.
"""


@dataclass(frozen=True, slots=True)
class DeskResult:
    """One desk's complete pass through the research lifecycle."""

    desk: Desk
    hypothesis_ref: str
    registration_ref: str
    run_ref: str
    verdict: Verdict
    calendar: str
    periods_per_year: int
    round_trip_bps: str
    universe: tuple[str, ...]
    excluded: tuple[str, ...]
    raw_sharpe: Decimal
    annualised: Comparable | None
    total_return: Decimal
    caveats: tuple[str, ...]
    power: PowerRequirement

    def describe(self) -> str:
        sharpe = (
            f"{self.annualised.value:+.4f}"
            if self.annualised is not None
            else f"{self.raw_sharpe} per bar"
        )
        return (
            f"{self.desk.value:<12} {self.verdict.value:<13} "
            f"ann.sharpe {sharpe:<10} return {self.total_return:+.4f}  "
            f"{self.calendar:<5} {self.power.bars_available}/"
            f"{self.power.bars_required} bars"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "desk": self.desk.value,
            "hypothesis": self.hypothesis_ref,
            "registration": self.registration_ref,
            "run": self.run_ref,
            "verdict": self.verdict.value,
            "calendar": self.calendar,
            "periods_per_year": self.periods_per_year,
            "round_trip_cost_bps": self.round_trip_bps,
            "universe": list(self.universe),
            "excluded_by_hindsight": list(self.excluded),
            "raw_sharpe": str(self.raw_sharpe),
            "annualised_sharpe": (
                self.annualised.as_payload() if self.annualised else None
            ),
            "total_return": str(self.total_return),
            "power": self.power.as_payload(),
            "is_live": False,
        }


@dataclass(frozen=True, slots=True)
class MultiDeskOutcome:
    """Seven desks, one question, and what putting them together showed."""

    results: tuple[DeskResult, ...]
    ranking_raw: tuple[str, ...]
    ranking_annualised: tuple[str, ...]
    reordered: bool
    refusals: tuple[str, ...]
    distortion: str
    """The widest gap between two desks' annualisation factors, named.

    Whether the *ranking* happens to change is luck -- it depends on where the
    seven raw numbers landed. Whether the comparison was distorted is not: the
    factors differ by a fixed ratio set by the calendars, and this states it
    whichever way the ranking came out."""

    budget_finding: str
    """What the power requirements said when put side by side."""

    @property
    def verdicts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.verdict.value] = counts.get(result.verdict.value, 0) + 1
        return counts

    @property
    def desks(self) -> int:
        return len(self.results)

    def describe(self) -> str:
        return (
            f"{self.desks} desks, verdicts {self.verdicts}; ranking "
            + ("changes" if self.reordered else "does not change")
            + f" once annualised; {self.distortion}"
        )

    @property
    def powered(self) -> tuple[str, ...]:
        return tuple(r.desk.value for r in self.results if r.power.powered)

    def as_payload(self) -> dict[str, Any]:
        return {
            "results": [r.as_payload() for r in self.results],
            "ranking_raw": list(self.ranking_raw),
            "ranking_annualised": list(self.ranking_annualised),
            "reordered": self.reordered,
            "distortion": self.distortion,
            "budget_finding": self.budget_finding,
            "refusals": list(self.refusals),
        }


def _spec(
    desk: Desk, *, bars: int | None = None, span: Decimal = SPAN_YEARS
) -> ExperimentSpec:
    """The same experiment, wearing each desk's own costs and clock.

    The bar count differs per desk **because the span does not**. The fixture
    steps one hour at a time and skips whatever the desk's calendar has closed,
    so the bars really are hourly and the declared interval is the truth rather
    than a label.
    """
    costs = costs_for(desk)
    interval = _INTERVAL
    count = bars if bars is not None else bars_for_span(
        desk.value, years=span, interval=interval
    )
    return ExperimentSpec(
        engine="local",
        universe=UniverseSpec(desk=desk.value, symbols=(), point_in_time=True),
        data=DataSpec(source=f"fixture:{desk.value}", bars=count, interval=interval),
        signal=SignalSpec(kind="momentum", lookback=_LOOKBACK),
        # The desk's real cost model, not a shared default. This is the single
        # most consequential difference between the seven runs: the same rule
        # pays 40bps a round trip on crypto and 760 on memecoins.
        backtest=BacktestSpec(costs=costs.engine_costs()),
        metrics=("total_return", "sharpe", "max_drawdown", "n_trades", "turnover"),
    )


def run_multi_desk(
    runtime: Runtime,
    *,
    span: Decimal = SPAN_YEARS,
    at: dt.datetime | None = None,
) -> MultiDeskOutcome:
    """Open every desk and drive one complete mission on each.

    ``span`` is the research budget **in years**, identical for every desk, and
    it is the only parameter. A shorter span produces the same shape of result
    over less data, which is what the tests use -- the finding is about how the
    seven desks relate to each other, and that does not depend on the budget.
    """
    moment = at or runtime.clock.now()

    with runtime.database.session() as session:
        runtime.desks.open_all(session, at=moment)
        openings = {row.desk: row for row in runtime.desks.opened(session)}

    results: list[DeskResult] = []
    refusals: list[str] = []

    for desk in DESKS:
        spec = _spec(desk, span=span)
        calendar = calendar_for(desk.value)
        costs = costs_for(desk)
        opening = openings[desk.value]
        power = required_observations(
            desk.value,
            annualised_claim=CLAIM,
            interval=spec.data.interval,
            bars_available=spec.data.bars,
        )

        with runtime.database.session() as session:
            hypothesis = runtime.research.propose(
                session,
                claim=(
                    f"A {_LOOKBACK}-bar momentum rule earns an annualised "
                    f"Sharpe of at least {CLAIM} on the {DESKS[desk].name} "
                    "desk after its own costs"
                ),
                author=_researcher(runtime, session),
                # Derived from the annualised claim through this desk's own
                # calendar, so the seven desks are asked the same question
                # rather than seven different ones wearing one number.
                minimum_effect=power.per_bar_effect,
                primary_metric="sharpe",
                family=f"momentum.{desk.value}",
                rationale=(
                    "The same annualised claim is asked on all seven desks "
                    "over the same span of time, so the answers mean the same "
                    f"thing. This desk charges {costs.round_trip_bps}bps a "
                    f"round trip, runs on the {calendar.name} calendar, and "
                    f"needs {power.bars_required} bars "
                    f"({power.years_required} years) to settle the claim."
                ),
                desk=desk.value,
                at=moment,
            )
            hypothesis_ref = hypothesis.ref
            runtime.research.screen(session, hypothesis_ref, at=moment)

            registration = runtime.research.register(
                session,
                hypothesis_ref=hypothesis_ref,
                spec=spec,
                pass_criteria=[
                    {
                        "metric": "sharpe",
                        "comparison": "gte",
                        "value": str(power.per_bar_effect),
                    }
                ],
                registrar=_registrar(runtime, session),
                analysis_plan=(
                    "Per-bar Sharpe from the local engine, annualised through "
                    f"the {calendar.name} calendar "
                    f"({calendar.periods_per_year(spec.data.interval)} "
                    f"{spec.data.interval} bars a year) before any cross-desk "
                    "comparison."
                ),
                at=moment,
            )
            registration_ref = registration.ref

            experiment = runtime.research.design(
                session,
                registration_ref=registration_ref,
                designer=_researcher(runtime, session),
                at=moment,
            )
            run, artifact = runtime.research.execute(
                session, experiment_ref=experiment.ref, at=moment
            )
            outcome = runtime.research.conclude(
                session,
                run_ref=run.ref,
                artifact=artifact,
                author=_researcher(runtime, session),
                interpretation=(
                    f"Momentum on {DESKS[desk].name} at "
                    f"{costs.round_trip_bps}bps round trip."
                ),
                at=moment,
            )

        sharpe = artifact.metrics.get("sharpe")
        try:
            converted: Comparable | None = annualise(
                sharpe, desk=desk.value, interval=spec.data.interval
            )
        except (Incomparable, KeyError) as exc:
            converted = None
            refusals.append(f"{desk.value}: {exc}")

        results.append(
            DeskResult(
                desk=desk,
                hypothesis_ref=hypothesis_ref,
                registration_ref=registration_ref,
                run_ref=run.ref,
                verdict=outcome.verdict,
                calendar=calendar.name,
                periods_per_year=opening.periods_per_year,
                round_trip_bps=str(costs.round_trip_bps),
                universe=tuple(artifact.diagnostics.get("universe", ())),
                excluded=tuple(artifact.diagnostics.get("excluded_by_hindsight", ())),
                raw_sharpe=sharpe.value,
                annualised=converted,
                total_return=artifact.metrics.get("total_return").value,
                caveats=tuple(opening.caveats),
                power=power,
            )
        )

    raw = tuple(
        r.desk.value
        for r in sorted(results, key=lambda r: r.raw_sharpe, reverse=True)
    )
    annual = tuple(
        r.desk.value
        for r in sorted(
            results,
            key=lambda r: r.annualised.value if r.annualised else Decimal("-999"),
            reverse=True,
        )
    )
    refusals.extend(_refusals(results))
    return MultiDeskOutcome(
        results=tuple(results),
        ranking_raw=raw,
        ranking_annualised=annual,
        reordered=raw != annual,
        distortion=_distortion(results),
        budget_finding=_budget_finding(results),
        refusals=tuple(refusals),
    )


def _budget_finding(results: list[DeskResult]) -> str:
    """The same claim, the same years, wildly different bar counts.

    The point is that the *years* agree and the *bars* do not. A company that
    handed every desk the same bar count would be giving its fastest-sampling
    desk a fraction of the time it gave its slowest, while appearing to treat
    them identically.
    """
    spans = {r.power.years_required for r in results}
    most = max(results, key=lambda r: r.power.bars_required)
    fewest = min(results, key=lambda r: r.power.bars_required)
    ratio = (
        Decimal(most.power.bars_required) / Decimal(fewest.power.bars_required)
    ).quantize(Decimal("0.01"))
    agreement = (
        f"the same {spans.pop()} years on every desk"
        if len(spans) == 1
        else f"between {min(spans)} and {max(spans)} years"
    )
    return (
        f"settling an annualised Sharpe of {results[0].power.annualised_claim} "
        f"takes {agreement} -- but {most.power.bars_required} bars on "
        f"{most.desk.value} and {fewest.power.bars_required} on "
        f"{fewest.desk.value}, a factor of {ratio}. A research budget stated "
        "in bars is not a budget."
    )


def _distortion(results: list[DeskResult]) -> str:
    """How far apart the seven conversion factors are.

    This is the number that makes the case, not the ranking. Whether the order
    happens to change depends on where seven noisy estimates landed; the
    distortion is a fixed property of the calendars, and it is there whether or
    not it reordered anything this time.
    """
    factors = [
        (r.desk.value, r.annualised.factor) for r in results if r.annualised
    ]
    if len(factors) < 2:  # pragma: no cover - every desk annualises
        return "no two desks could be converted"
    low = min(factors, key=lambda pair: pair[1])
    high = max(factors, key=lambda pair: pair[1])
    ratio = (high[1] / low[1]).quantize(Decimal("0.01"))
    return (
        f"the same per-bar Sharpe is worth {ratio}x more on {high[0]} than on "
        f"{low[0]} once annualised"
    )


def _refusals(results: list[DeskResult]) -> list[str]:
    """Comparisons the company will not make, exercised rather than described.

    Two of them, and both are refusals a looser system would make silently: a
    trade count is not a rate, and two measurements taken over very different
    windows are not comparable no matter how carefully each was converted.
    """
    from aurelis.desks.comparability import compare

    out: list[str] = []
    try:
        annualise(
            "n_trades", Decimal(40), desk=results[0].desk.value, interval="1d"
        )
    except Incomparable as exc:
        out.append(f"n_trades across desks: {exc}")

    if len(results) >= 2:
        left, right = results[0], results[1]
        if left.annualised and right.annualised:
            try:
                compare(
                    left.annualised,
                    right.annualised,
                    bars=(
                        left.power.bars_available,
                        left.power.bars_available * 5,
                    ),
                )
            except Incomparable as exc:
                out.append(f"mismatched windows: {exc}")
    return out


def _researcher(runtime: Runtime, session: Any) -> str:
    return runtime.roster.by_handle(session, "QUANT").ref


def _registrar(runtime: Runtime, session: Any) -> str:
    return runtime.roster.by_handle(session, "GOV").ref
