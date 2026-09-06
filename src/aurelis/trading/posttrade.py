"""Post-trade analysis, and the measurement reality gets a vote on.

Two things happen here and they answer different questions.

:meth:`PostTrade.analyse` looks at one order: what price the strategy expected,
what it got, and what that cost. Slippage and fees are kept apart because "the
costs were higher than modelled" and "we were filled worse than modelled" are
different failures with different fixes, and one combined cost number hides
which happened.

:meth:`PostTrade.measure_gap` looks at a whole deployment: the backtest said
this, paper produced that, and the difference is the gap. It is the most
valuable measurement in the company because it is the only one where the
company's own claim is checked by something it does not control.

The expectation is **copied from the run that supported the promotion**, with
its artifact digest, rather than recomputed. Re-deriving it would compare paper
against today's best estimate instead of against the number that actually
justified deployment — which is the comparison that would tell the company it
had been wrong.

And the gap is tracked as a **company competence**. How wrong our backtests
tend to be is a fact about us, not about any one strategy, which is why
:meth:`PostTrade.company_gap` aggregates across versions.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import uuid7
from aurelis.platform.ledger.ledger import Ledger
from aurelis.research.tables import Result, Run
from aurelis.trading.tables import Fill, GapMeasurement, Order, PostTradeReport

__all__ = ["DIRECTIONS", "Direction", "Gap", "PostTrade", "Slippage"]

_BPS = Decimal("10000")


class Direction(StrEnum):
    """Which way is good, for one metric.

    Needed because "the gap held" is not a statement about arithmetic. A paper
    drawdown *below* the backtest's is the deployment beating expectation; a
    paper Sharpe below it is the opposite. An earlier version compared
    ``realised - expected >= 0`` for everything and reported a deployment that
    beat its drawdown estimate as having fallen short.
    """

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    NEUTRAL = "neutral"
    """Descriptive. A gap can be measured and reported; "held" has no meaning,
    and asking for one raises rather than guessing."""


DIRECTIONS: dict[str, Direction] = {
    "total_return": Direction.HIGHER_IS_BETTER,
    "sharpe": Direction.HIGHER_IS_BETTER,
    "deflated_sharpe": Direction.HIGHER_IS_BETTER,
    "max_drawdown": Direction.LOWER_IS_BETTER,
    "cost_drag": Direction.LOWER_IS_BETTER,
    "slippage_bps": Direction.LOWER_IS_BETTER,
    "turnover": Direction.NEUTRAL,
    "n_trades": Direction.NEUTRAL,
}
"""Which way is good, per metric.

An explicit table rather than a naming convention. A metric absent from it
raises instead of defaulting, because a silently-assumed direction is exactly
how a deployment that beat its estimate gets recorded as having missed it.
"""


@dataclass(frozen=True, slots=True)
class Slippage:
    """One order's execution quality."""

    order_ref: str
    expected_price: Decimal
    fill_price: Decimal
    slippage: Decimal
    slippage_bps: Decimal
    fees: Decimal
    modelled_cost_bps: Decimal
    realised_cost_bps: Decimal

    @property
    def cost_surprise_bps(self) -> Decimal:
        """Positive means the cost model was optimistic — the direction that
        matters, because it is the one that turns a backtest edge into
        nothing."""
        return self.realised_cost_bps - self.modelled_cost_bps

    def describe(self) -> str:
        return (
            f"{self.order_ref}: filled at {self.fill_price} against an expected "
            f"{self.expected_price} ({self.slippage_bps}bps), costs "
            f"{self.realised_cost_bps}bps against {self.modelled_cost_bps}bps "
            f"modelled"
        )


@dataclass(frozen=True, slots=True)
class Gap:
    """What the backtest claimed against what paper produced."""

    version_ref: str
    metric: str
    expected: Decimal
    realised: Decimal
    observations: int
    expected_source: str

    @property
    def gap(self) -> Decimal:
        """``realised - expected``. Signed arithmetic, direction-agnostic."""
        return self.realised - self.expected

    @property
    def direction(self) -> Direction:
        try:
            return DIRECTIONS[self.metric]
        except KeyError:
            raise IntegrityViolation(
                f"no direction is recorded for {self.metric!r}, so whether its "
                "gap held cannot be decided. Add it to DIRECTIONS rather than "
                "letting the comparison guess"
            ) from None

    @property
    def held(self) -> bool:
        """Whether paper did at least as well as the backtest promised.

        Reads the metric's direction: a paper drawdown *below* the backtest's
        is the deployment beating expectation, and a paper Sharpe below it is
        the opposite.
        """
        if self.direction is Direction.LOWER_IS_BETTER:
            return self.gap <= 0
        if self.direction is Direction.HIGHER_IS_BETTER:
            return self.gap >= 0
        raise IntegrityViolation(
            f"{self.metric} is descriptive; its gap is worth reporting but "
            "'held' is not a question it can answer"
        )

    def describe(self) -> str:
        if self.direction is Direction.NEUTRAL:
            verdict = "descriptive"
        else:
            verdict = "held" if self.held else "fell short"
        return (
            f"{self.version_ref} {self.metric}: backtest {self.expected}, "
            f"paper {self.realised} ({self.gap:+}) — {verdict}"
        )


class PostTrade:
    """Execution quality, cost attribution, and the backtest-live gap."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # ------------------------------------------------------- one order

    def analyse(
        self,
        session: Session,
        *,
        order_ref: str,
        analysed_by: str,
        modelled_cost_bps: Decimal = Decimal("15"),
        at: dt.datetime | None = None,
    ) -> PostTradeReport:
        """Compare one order's fill against what the strategy assumed."""
        moment = at or self._clock.now()
        order = session.execute(
            sa.select(Order).where(Order.ref == order_ref)
        ).scalar_one_or_none()
        if order is None:
            raise IntegrityViolation(f"no order {order_ref}")

        fills = list(
            session.execute(sa.select(Fill).where(Fill.order_ref == order_ref)).scalars()
        )
        if not fills:
            raise IntegrityViolation(
                f"{order_ref} has no fill; there is nothing to analyse, and a "
                "report over an unfilled order would invent an execution"
            )

        quantity = sum((fill.quantity for fill in fills), Decimal(0))
        notional = sum((fill.quantity * fill.price for fill in fills), Decimal(0))
        fees = sum((fill.fee for fill in fills), Decimal(0))
        average = notional / quantity

        signed = Decimal(1) if order.side == "buy" else Decimal(-1)
        slip = (average - order.expected_price) * signed
        slip_bps = (slip / order.expected_price * _BPS).quantize(Decimal("0.0001"))
        fee_bps = (fees / notional * _BPS).quantize(Decimal("0.0001"))
        realised_bps = (slip_bps + fee_bps).quantize(Decimal("0.0001"))

        report = PostTradeReport(
            report_id=uuid7(),
            order_ref=order_ref,
            version_ref=order.version_ref,
            expected_price=order.expected_price,
            fill_price=average.quantize(Decimal("0.00000001")),
            slippage=slip.quantize(Decimal("0.00000001")),
            slippage_bps=slip_bps,
            fees=fees,
            modelled_cost_bps=modelled_cost_bps,
            realised_cost_bps=realised_bps,
            cost_surprise_bps=(realised_bps - modelled_cost_bps),
            analysed_by=analysed_by,
            analysed_at=moment,
        )
        session.add(report)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.POST_TRADE_ANALYSED,
            actor=analysed_by,
            subject=order_ref,
            payload={
                "expected_price": str(order.expected_price),
                "fill_price": str(report.fill_price),
                "slippage_bps": str(slip_bps),
                "realised_cost_bps": str(realised_bps),
                "modelled_cost_bps": str(modelled_cost_bps),
                "cost_surprise_bps": str(report.cost_surprise_bps),
            },
            at=moment,
        )
        return report

    # -------------------------------------------------- the whole claim

    def expectation(
        self, session: Session, *, run_ref: str, metric: str
    ) -> tuple[Decimal, str]:
        """Read what the backtest claimed, from the run that claimed it.

        Returns the value and the artifact digest it came from, so a gap cites
        the exact number that justified deployment rather than a fresh estimate
        of it.
        """
        row = session.execute(
            sa.select(Result).where(
                Result.run_ref == run_ref, Result.metric == metric
            )
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(
                f"{run_ref} has no {metric}; a gap against an expectation that "
                "was never measured would be a comparison with nothing"
            )
        return row.value, row.artifact_digest

    def measure_gap(
        self,
        session: Session,
        *,
        version_ref: str,
        portfolio_ref: str,
        desk: str,
        metric: str,
        run_ref: str,
        realised: Decimal,
        period_start: dt.datetime,
        period_end: dt.datetime,
        observations: int,
        realised_source: str,
        at: dt.datetime | None = None,
    ) -> Gap:
        """Record backtest expectation against what paper actually produced."""
        moment = at or self._clock.now()
        expected, digest = self.expectation(session, run_ref=run_ref, metric=metric)

        existing = session.execute(
            sa.select(GapMeasurement).where(
                GapMeasurement.version_ref == version_ref,
                GapMeasurement.metric == metric,
                GapMeasurement.period_end == period_end,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return Gap(
                version_ref,
                metric,
                existing.expected,
                existing.realised,
                existing.observations,
                existing.expected_source,
            )

        gap = Gap(version_ref, metric, expected, realised, observations, digest)
        session.add(
            GapMeasurement(
                measurement_id=uuid7(),
                version_ref=version_ref,
                portfolio_ref=portfolio_ref,
                desk=desk,
                metric=metric,
                expected=expected,
                realised=realised,
                gap=gap.gap,
                period_start=period_start,
                period_end=period_end,
                observations=observations,
                expected_source=digest,
                realised_source=realised_source,
                payload={"run_ref": run_ref},
                measured_at=moment,
            )
        )
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.GAP_MEASURED,
            actor="system",
            subject=version_ref,
            payload={
                "metric": metric,
                "expected": str(expected),
                "realised": str(realised),
                "gap": str(gap.gap),
                "direction": gap.direction.value,
                "held": (
                    None if gap.direction is Direction.NEUTRAL else gap.held
                ),
                "observations": observations,
                "expected_source": digest[:16],
            },
            at=moment,
        )
        return gap

    @staticmethod
    def as_gap(row: GapMeasurement) -> Gap:
        """Read a stored measurement back as a :class:`Gap`.

        One implementation of "did it hold?", so a reader — a CLI, the station,
        a report — cannot recompute it direction-blind. The first version of
        the CLI did exactly that and printed *held: yes* next to a measurement
        the Gap object called falling short.
        """
        return Gap(
            version_ref=row.version_ref,
            metric=row.metric,
            expected=row.expected,
            realised=row.realised,
            observations=row.observations,
            expected_source=row.expected_source,
        )

    def gaps(
        self, session: Session, *, version_ref: str | None = None
    ) -> list[GapMeasurement]:
        query = sa.select(GapMeasurement).order_by(GapMeasurement.period_end)
        if version_ref:
            query = query.where(GapMeasurement.version_ref == version_ref)
        return list(session.execute(query).scalars())

    def company_gap(self, session: Session, metric: str) -> Decimal | None:
        """The mean gap across every deployment, for one metric.

        A company-level competence rather than a strategy property: this is how
        wrong *our* backtests tend to be. Returns ``None`` when nothing has
        been measured, because a mean of no observations is not zero.
        """
        rows = list(
            session.execute(
                sa.select(GapMeasurement.gap).where(GapMeasurement.metric == metric)
            ).scalars()
        )
        if not rows:
            return None
        values = [Decimal(str(value)) for value in rows]
        return (sum(values, Decimal(0)) / len(values)).quantize(Decimal("0.00000001"))

    def supporting_run(self, session: Session, version_ref: str) -> str | None:
        """The most recent completed run on this version's desk.

        A convenience for the paper cycle, and deliberately explicit about
        being a *convenience*: a deployment should name the run that justified
        it, and this is a fallback for demonstrations rather than a source of
        truth.
        """
        return session.execute(
            sa.select(Run.ref)
            .where(Run.status == "completed")
            .order_by(Run.started_at.desc())
            .limit(1)
        ).scalar()
