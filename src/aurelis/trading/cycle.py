"""The paper cycle: one turn of trading operations, end to end.

Runs the chain from `docs/05-lifecycles.md` §6 in order — market setup, trade
planning, approval check, execution, position monitoring, post-trade — and
records what happened at every step. Each stage can refuse, and a refusal is a
result rather than an exception: "the desk was halted" and "the strategy asked
for nothing" are both legitimate outcomes of a cycle that ran correctly.

Deliberately **not** an orchestrator. The cycle does not decide anything: it
asks Risk what is permitted, asks the broker what happened, and writes both
down. Every judgement in it belongs to a component that already existed.

The forecast is the part worth noticing. A deployment records a probability
that its own backtest-live gap will hold, and the first completed period scores
it. Over deployments that produces a calibration for a claim the company makes
constantly and rarely checks: *our backtests are approximately right*.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.alerts.service import Alerts, Severity
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.ids import uuid7
from aurelis.meetings.tables import Forecast
from aurelis.platform.ledger.ledger import Ledger
from aurelis.portfolio.construction import Book
from aurelis.risk.authority import Risk
from aurelis.risk.tables import TradeProposal
from aurelis.trading.brokers import BrokerAdapter
from aurelis.trading.execution import Execution
from aurelis.trading.posttrade import Gap, PostTrade
from aurelis.trading.states import OrderSide
from aurelis.trading.tables import Order

__all__ = ["CycleOutcome", "GAP_QUESTION", "PaperCycle", "record_gap_forecast"]

GAP_QUESTION = (
    "Will this deployment's realised return be at least as good as its "
    "backtest expectation over the first full period?"
)
"""The forecast every deployment records.

Binary and settleable from the record, which is what makes it worth asking. A
richer question — "how large will the gap be?" — cannot be scored with a Brier
score, and an unscored forecast teaches nobody anything.
"""


@dataclass(frozen=True, slots=True)
class CycleOutcome:
    """What one turn of the cycle did, including the steps it refused."""

    ran_at: dt.datetime
    portfolio_ref: str
    proposals: tuple[str, ...] = ()
    orders: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    reports: tuple[str, ...] = ()
    alerts: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def executed(self) -> int:
        return len(self.orders)

    def describe(self) -> str:
        lines = [
            f"paper cycle on {self.portfolio_ref} at {self.ran_at:%Y-%m-%d %H:%M}",
            f"  proposed   {len(self.proposals)}",
            f"  executed   {len(self.orders)}",
            f"  refused    {len(self.refused)}",
            f"  analysed   {len(self.reports)}",
        ]
        if self.alerts:
            lines.append(f"  alerts     {', '.join(self.alerts)}")
        lines.extend(f"  · {note}" for note in self.notes)
        return "\n".join(lines)


class PaperCycle:
    """One scheduled turn of trading operations."""

    __slots__ = ("_alerts", "_book", "_clock", "_execution", "_ledger", "_posttrade", "_risk")

    def __init__(
        self,
        *,
        risk: Risk,
        execution: Execution,
        posttrade: PostTrade,
        book: Book,
        alerts: Alerts,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)
        self._risk = risk
        self._execution = execution
        self._posttrade = posttrade
        self._book = book
        self._alerts = alerts

    def run(
        self,
        session: Session,
        *,
        portfolio_ref: str,
        broker: BrokerAdapter,
        intents: tuple[tuple[str, str, OrderSide, Decimal, Decimal], ...],
        proposer: str,
        assessor: str,
        approver: str,
        executor: str,
        analyst: str,
        at: dt.datetime | None = None,
    ) -> CycleOutcome:
        """Run one turn.

        ``intents`` are ``(version_ref, symbol, side, exposure, price)`` — what
        the strategies would like. Nothing in that tuple is a decision: every
        one of them goes to Risk before it becomes anything.
        """
        moment = at or self._clock.now()
        proposals: list[str] = []
        orders: list[str] = []
        refused: list[str] = []
        reports: list[str] = []
        raised: list[str] = []
        notes: list[str] = []

        for version_ref, symbol, side, exposure, price in intents:
            desk = self._desk_of(session, version_ref)
            proposal = TradeProposal(
                proposal_id=uuid7(),
                ref=self._next_proposal_ref(session),
                portfolio_ref=portfolio_ref,
                version_ref=version_ref,
                desk=desk,
                symbol=symbol,
                side=side.value,
                desired_exposure=exposure,
                rationale=f"paper cycle intent for {version_ref}",
                proposed_by=proposer,
                proposed_at=moment,
            )
            session.add(proposal)
            session.flush()
            proposals.append(proposal.ref)

            assessment = self._risk.assess(
                session, proposal_ref=proposal.ref, assessor=assessor, at=moment
            )
            if assessment.allowed_exposure <= 0:
                refused.append(proposal.ref)
                notes.append(
                    f"{proposal.ref} {assessment.decision}: {assessment.reason[:90]}"
                )
                alert = self._alerts.raise_alert(
                    session,
                    severity=Severity.WARNING,
                    source="trading.paper_cycle",
                    subject=version_ref,
                    desk=desk,
                    message=(
                        f"Risk {assessment.decision} the paper intent for "
                        f"{version_ref} on {symbol}"
                    ),
                    recommended_action=(
                        "Read the assessment's reason; if the limit is stale, "
                        "convene a Risk Committee to revisit it"
                    ),
                    raised_by=assessor,
                    evidence={"assessment": assessment.ref, "proposal": proposal.ref},
                    at=moment,
                )
                raised.append(alert.ref)
                continue

            approval = self._risk.approve(
                session, proposal_ref=proposal.ref, approver=approver, at=moment
            )
            quantity = (approval.final_target / price).quantize(Decimal("0.00000001"))
            if quantity <= 0:
                refused.append(proposal.ref)
                notes.append(f"{proposal.ref}: approved size rounds to zero at {price}")
                continue

            executed = self._execution.submit(
                session,
                approval_ref=approval.ref,
                broker=broker,
                symbol=symbol,
                quantity=quantity,
                expected_price=price,
                submitted_by=executor,
                at=moment,
            )
            if not executed.filled:
                refused.append(executed.order.ref)
                notes.append(executed.describe())
                continue

            orders.append(executed.order.ref)
            report = self._posttrade.analyse(
                session,
                order_ref=executed.order.ref,
                analysed_by=analyst,
                at=moment,
            )
            reports.append(str(report.report_id))
            if report.cost_surprise_bps > 0:
                notes.append(
                    f"{executed.order.ref}: costs came in "
                    f"{report.cost_surprise_bps}bps above the model"
                )

        self._ledger.append(
            session,
            kind=EventKind.PAPER_CYCLE_RAN,
            actor="system",
            subject=portfolio_ref,
            payload={
                "proposed": len(proposals),
                "executed": len(orders),
                "refused": len(refused),
                "broker": broker.kind.value,
            },
            at=moment,
        )
        return CycleOutcome(
            ran_at=moment,
            portfolio_ref=portfolio_ref,
            proposals=tuple(proposals),
            orders=tuple(orders),
            refused=tuple(refused),
            reports=tuple(reports),
            alerts=tuple(raised),
            notes=notes,
        )

    # ---------------------------------------------------------- helpers

    @staticmethod
    def _desk_of(session: Session, version_ref: str) -> str:
        from aurelis.strategy.tables import StrategyVersion

        desk = session.execute(
            sa.select(StrategyVersion.desk).where(StrategyVersion.ref == version_ref)
        ).scalar()
        return str(desk or "unknown")

    @staticmethod
    def _next_proposal_ref(session: Session) -> str:
        from aurelis.core.ids import RefKind
        from aurelis.platform.db.refs import allocate_ref

        return allocate_ref(session, RefKind.TRADE_PROPOSAL)


def record_gap_forecast(
    session: Session,
    *,
    meeting_ref: str,
    agent_ref: str,
    probability: Decimal,
    reasoning: str,
    at: dt.datetime,
) -> Forecast:
    """Record a deployment's forecast of its own backtest-live gap.

    Attached to the meeting that promoted the version, so it sits with the
    decision it qualifies rather than in a table of its own. Scored later by
    the ordinary :class:`~aurelis.meetings.forecasts.ForecastScorer` against
    the first completed period.
    """
    forecast = Forecast(
        forecast_id=uuid7(),
        meeting_ref=meeting_ref,
        agent_ref=agent_ref,
        question=GAP_QUESTION,
        probability=probability,
        reasoning=reasoning,
        recorded_at=at,
    )
    session.add(forecast)
    session.flush()
    return forecast


def gap_outcome(gaps: tuple[Gap, ...]) -> bool:
    """Whether a deployment's gaps held, for scoring the forecast.

    Every measured metric must have held. A deployment whose return held while
    its drawdown blew out did not meet its backtest expectation, and scoring it
    as a success would teach the company the wrong lesson about its own
    optimism.
    """
    return bool(gaps) and all(gap.held for gap in gaps)


def open_orders(session: Session, portfolio_ref: str) -> list[Order]:
    return list(
        session.execute(
            sa.select(Order).where(
                Order.portfolio_ref == portfolio_ref,
                Order.status == "submitted",
            )
        ).scalars()
    )
