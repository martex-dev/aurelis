"""A calibrated mechanism trades on paper, through the same chain as anything else.

Only a **candidate scheme** trades: a mechanism with enough scored
out-of-sample predictions that beat a coin toss and the instrument's own
base rate. Until then it gathers evidence and moves no money, paper or
otherwise.

When it does trade, nothing is special-cased. The mechanism is composed into
a strategy version through :class:`~aurelis.strategy.synthesis.Synthesis`
(origin ``INVENTED``, rationale the mechanism's own why, weakness its decay
model), given a share of the paper book, and every firing becomes an intent
that goes through Risk, approval, execution and post-trade analysis —
:class:`~aurelis.trading.cycle.PaperCycle`, unchanged. Risk can refuse it.
A position is opened at the reference close of the firing and closed at the
resolution close when the prediction scores, so a mechanism's paper P&L is
the sum of round trips it was actually right and wrong on, after fees.

P&L is reported, not judged: over a short window it is mostly luck, and the
mandate does not read it. The calibration record is the measure; the paper
book is where a calibrated mechanism shows what that calibration is worth
after costs.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import isoformat
from aurelis.core.enums import EventKind
from aurelis.core.ids import uuid7
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.tables import Mechanism, MechanismTrade
from aurelis.org.desks import Desk
from aurelis.strategy.states import ComponentKind, Origin
from aurelis.trading.states import BrokerKind, OrderSide
from aurelis.trading.tables import Fill, Order

__all__ = ["DEFAULT_WEIGHT", "PaperResult", "ensure_version", "pnl_of", "trade_firings"]

DEFAULT_WEIGHT = Decimal("0.05")
"""Share of the paper book one scheme is given. Small on purpose: a scheme
that just cleared the bar has a record measured in tens of predictions."""


@dataclass(frozen=True, slots=True)
class PaperResult:
    mechanism_ref: str
    opened: tuple[str, ...]
    closed: tuple[str, ...]
    refused: tuple[str, ...]
    note: str

    def describe(self) -> str:
        return (
            f"{self.mechanism_ref}: opened {len(self.opened)}, closed {len(self.closed)}, "
            f"refused {len(self.refused)}" + (f"; {self.note}" if self.note else "")
        )


def ensure_version(runtime: Any, session: Session, mechanism: Mechanism, *, at: dt.datetime) -> str:
    """The strategy version a mechanism trades as, composed once.

    Composed through the synthesis surface with the mechanism as the cited
    origin, so the strategy registry shows a version whose signal component
    is the mechanism's rule and whose known weakness is its decay model.
    """
    if mechanism.version_ref:
        return str(mechanism.version_ref)
    desk = Desk(mechanism.desk)
    # An invented component cites the work it was invented under. The
    # composition is that work: a task, assigned to the mechanism's own agent,
    # whose payload names the mechanism.
    from aurelis.core.enums import Actor

    # The researcher who stated the mechanism does not compose the strategy:
    # writing a component or a version is the Strategy Architect's scope, and
    # the write-scope guard refuses anyone else. The mechanism is the
    # researcher's; the version is the architect's composition of it, and the
    # component's spec names the mechanism so the provenance runs both ways.
    architect = _architect(runtime, session)
    task = runtime.queue.enqueue(
        session,
        kind="mechanism.compose",
        assignee=architect,
        payload={"mechanism": mechanism.ref, "stated_by": mechanism.agent_ref},
        actor=Actor.SYSTEM,
        at=at,
    )
    strategy = runtime.synthesis.open_strategy(
        session,
        name=f"mechanism {mechanism.ref}: {mechanism.title[:60]}",
        thesis=mechanism.why,
        desk=desk,
        owner=architect,
        at=at,
    )
    component = runtime.synthesis.author_component(
        session,
        kind=ComponentKind.SIGNAL,
        name=f"{mechanism.trigger_kind} -> {mechanism.direction} {mechanism.horizon_hours}h",
        spec={
            "mechanism": mechanism.ref,
            "trigger": mechanism.trigger_kind,
            "direction": mechanism.direction,
            "horizon_hours": mechanism.horizon_hours,
            "confidence": str(mechanism.confidence),
        },
        rationale=mechanism.why,
        origin=Origin.INVENTED,
        origin_ref=task.ref,
        author=architect,
        desk=desk,
        at=at,
    )
    version = runtime.synthesis.compose(
        session,
        strategy_ref=strategy.ref,
        components=(component,),
        universe={"instruments": "any the trigger fires on", "desk": mechanism.desk},
        cost_model={"fee_bps": "10", "spread_bps": "5"},
        known_weaknesses=(mechanism.decay,),
        author=architect,
        risk_assumptions=mechanism.other_side,
        at=at,
    )
    mechanism.version_ref = version.version.ref
    session.flush()
    return str(version.version.ref)


_ARCHITECT_CHARTERS: tuple[str, ...] = ("strategy.architect", "strategy.synthesizer")


def _architect(runtime: Any, session: Session) -> str:
    """The agent whose charter may write a component and compose a version."""
    from aurelis.agents.tables import AgentState
    from aurelis.core.errors import IntegrityViolation

    for agent in runtime.roster.all(session):
        if agent.state not in (AgentState.ACTIVE, AgentState.WORKING):
            continue
        if any(held in _ARCHITECT_CHARTERS for held in agent.coverage):
            return str(agent.ref)
    raise IntegrityViolation(
        "no active agent holds the strategy architect or synthesizer charter, so "
        "nobody may compose a mechanism into a version"
    )


def _actors(runtime: Any, session: Session) -> dict[str, str]:
    return {
        role: runtime.roster.by_handle(session, handle).ref
        for role, handle in (
            ("proposer", "PM"),
            ("assessor", "RISK"),
            ("approver", "TRADE"),
            ("executor", "TRADE"),
            ("analyst", "TRADE"),
            ("portfolio", "PM"),
        )
    }


def trade_firings(
    runtime: Any,
    session: Session,
    mechanism: Mechanism,
    *,
    equity: Decimal = Decimal("100000"),
    weight: Decimal = DEFAULT_WEIGHT,
    at: dt.datetime | None = None,
) -> PaperResult:
    """Open a paper position on every unopened firing and close every scored one.

    Called only for a candidate scheme; the caller checks. Everything below
    goes through the ordinary chain and Risk may refuse any of it.
    """
    from aurelis.trading.deployment import open_paper_book

    moment = at or runtime.clock.now()
    actors = _actors(runtime, session)
    version_ref = ensure_version(runtime, session, mechanism, at=moment)
    book = open_paper_book(
        runtime,
        session,
        desk=mechanism.desk,
        equity=equity,
        opened_by=actors["portfolio"],
        at=moment,
    )
    if not any(a.version_ref == version_ref for a in runtime.book.allocations(session, book)):
        runtime.book.allocate(
            session,
            portfolio_ref=book,
            version_ref=version_ref,
            weight=weight,
            rationale=(
                f"{mechanism.ref} is a candidate scheme: its out-of-sample predictions "
                "beat a coin toss and the base rate. A small share, because the record "
                "is measured in tens of predictions"
            ),
            decided_by=actors["portfolio"],
            at=moment,
        )
    exposure = equity * weight
    broker = runtime.brokers[BrokerKind.PAPER]

    opened: list[str] = []
    closed: list[str] = []
    refused: list[str] = []

    # Firings not yet opened: a prediction sealed, not training, no trade row.
    firings = list(
        session.execute(
            sa.select(Thesis)
            .where(
                Thesis.mechanism_ref == mechanism.ref,
                Thesis.mechanism_training.is_(False),
                ~sa.exists().where(MechanismTrade.thesis_ref == Thesis.ref),
            )
            .order_by(Thesis.ref)
        ).scalars()
    )
    for thesis in firings:
        if thesis.scored_at is not None:
            continue  # its horizon already passed unopened; a round trip now would be hindsight
        price = Decimal(thesis.reference_close)
        side = OrderSide.BUY if thesis.direction == "up" else OrderSide.SELL
        broker.marks[thesis.instrument] = price
        outcome = runtime.cycle.run(
            session,
            portfolio_ref=book,
            broker=broker,
            intents=((version_ref, thesis.instrument, side, exposure, price),),
            proposer=actors["proposer"],
            assessor=actors["assessor"],
            approver=actors["approver"],
            executor=actors["executor"],
            analyst=actors["analyst"],
            at=moment,
        )
        if not outcome.orders:
            refused.append(thesis.ref)
            continue
        session.add(
            MechanismTrade(
                trade_id=uuid7(),
                mechanism_ref=mechanism.ref,
                thesis_ref=thesis.ref,
                portfolio_ref=book,
                open_order_ref=outcome.orders[0],
                opened_at=moment,
            )
        )
        session.flush()
        opened.append(thesis.ref)

    # Open trades whose prediction has scored: close at the resolution close.
    to_close = list(
        session.execute(
            sa.select(MechanismTrade, Thesis)
            .join(Thesis, Thesis.ref == MechanismTrade.thesis_ref)
            .where(
                MechanismTrade.mechanism_ref == mechanism.ref,
                MechanismTrade.close_order_ref.is_(None),
                Thesis.scored_at.is_not(None),
            )
        ).all()
    )
    for trade, thesis in to_close:
        price = Decimal(thesis.resolution_close or thesis.reference_close)
        side = OrderSide.SELL if thesis.direction == "up" else OrderSide.BUY
        broker.marks[thesis.instrument] = price
        outcome = runtime.cycle.run(
            session,
            portfolio_ref=book,
            broker=broker,
            intents=((version_ref, thesis.instrument, side, exposure, price),),
            proposer=actors["proposer"],
            assessor=actors["assessor"],
            approver=actors["approver"],
            executor=actors["executor"],
            analyst=actors["analyst"],
            at=moment,
        )
        if not outcome.orders:
            refused.append(thesis.ref)
            continue
        trade.close_order_ref = outcome.orders[0]
        trade.closed_at = moment
        trade.pnl = _round_trip_pnl(session, trade.open_order_ref, trade.close_order_ref)
        session.flush()
        closed.append(thesis.ref)

    if opened or closed:
        runtime.ledger.append(
            session,
            kind=EventKind.MECHANISM_TRADED,
            actor=actors["executor"],
            subject=mechanism.ref,
            payload={
                "version": version_ref,
                "book": book,
                "opened": len(opened),
                "closed": len(closed),
                "refused": len(refused),
                "at": isoformat(moment),
            },
            at=moment,
        )
    return PaperResult(mechanism.ref, tuple(opened), tuple(closed), tuple(refused), "")


def _fill(session: Session, order_ref: str) -> tuple[Order, Fill] | None:
    order = session.execute(sa.select(Order).where(Order.ref == order_ref)).scalar_one_or_none()
    if order is None:
        return None
    fill = (
        session.execute(sa.select(Fill).where(Fill.order_ref == order_ref).order_by(Fill.filled_at))
        .scalars()
        .first()
    )
    if fill is None:
        return None
    return order, fill


def _round_trip_pnl(session: Session, open_ref: str, close_ref: str) -> Decimal:
    """Realised P&L of one round trip, after fees. Long: sold minus bought."""
    opened = _fill(session, open_ref)
    closed = _fill(session, close_ref)
    if opened is None or closed is None:
        return Decimal(0)
    order_o, fill_o = opened
    _, fill_c = closed
    quantity = min(Decimal(str(fill_o.quantity)), Decimal(str(fill_c.quantity)))
    sign = Decimal(1) if order_o.side == OrderSide.BUY.value else Decimal(-1)
    gross = sign * (Decimal(str(fill_c.price)) - Decimal(str(fill_o.price))) * quantity
    fees = Decimal(str(fill_o.fee)) + Decimal(str(fill_c.fee))
    return (gross - fees).quantize(Decimal("0.01"))


def pnl_of(session: Session, mechanism_ref: str) -> dict[str, Any]:
    rows = list(
        session.execute(
            sa.select(MechanismTrade).where(MechanismTrade.mechanism_ref == mechanism_ref)
        ).scalars()
    )
    closed = [r for r in rows if r.close_order_ref is not None]
    total = sum((Decimal(str(r.pnl or 0)) for r in closed), Decimal(0))
    return {
        "trades": len(rows),
        "open": len(rows) - len(closed),
        "closed": len(closed),
        "won": sum(1 for r in closed if Decimal(str(r.pnl or 0)) > 0),
        "pnl": total.quantize(Decimal("0.01")),
    }
