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
from decimal import ROUND_UP, Decimal
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

__all__ = [
    "DEFAULT_WEIGHT",
    "LIQUIDITY_SHARE",
    "MIN_POSITION_USD",
    "books_with_trades",
    "flatten_book",
    "PaperResult",
    "close_settled",
    "ensure_version",
    "has_open_trades",
    "pnl_of",
    "trade_firings",
]

LIQUIDITY_SHARE = Decimal("0.02")
"""The most of a token's pool a paper position may claim to have traded.

A memecoin pool with $20,000 in it does not fill a $5,000 order at the
price on the screen; claiming it did would make every token round trip a
fiction. A position in a token keyed by chain and contract is capped at
this share of the liquidity its newest attention event reported (M45)."""

MIN_POSITION_USD = Decimal("100")
"""Below this, the capped position is too small to be worth its fees."""

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
        cost_model=_cost_model_of(mechanism.desk),
        known_weaknesses=(mechanism.decay,),
        author=architect,
        risk_assumptions=mechanism.other_side,
        at=at,
    )
    mechanism.version_ref = version.version.ref
    session.flush()
    return str(version.version.ref)


_ARCHITECT_CHARTERS: tuple[str, ...] = ("strategy.architect", "strategy.synthesizer")


def _cost_model_of(desk: str) -> dict[str, str]:
    """The desk's own costs on the version, so the record of what the paper
    fills paid and the record of what the version declared agree."""
    from aurelis.desks.costs import costs_for

    try:
        model = costs_for(desk)
    except (KeyError, ValueError):
        model = costs_for("crypto")
    return {
        "fee_bps": str(model.commission_bps),
        "spread_bps": str(model.spread_bps),
        "impact_bps": str(model.slippage_bps),
        "desk": desk,
    }


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
    notes: list[str] = []
    for thesis in firings:
        if thesis.scored_at is not None:
            continue  # its horizon already passed unopened; a round trip now would be hindsight
        # The fill is at the newest close the wake can see, never the
        # trigger's: the order is placed now, and now may be an hour later.
        known = _executable_price(session, thesis.instrument, moment)
        if known is None or known[1] < _aware(thesis.reference_at):
            refused.append(thesis.ref)
            notes.append(f"{thesis.ref}: no recorded price as new as the trigger; not opened")
            continue
        price, bar_at = known
        size = exposure
        if ":" in thesis.instrument:
            liquidity = _liquidity_of(session, thesis.instrument)
            if liquidity is None:
                refused.append(thesis.ref)
                notes.append(f"{thesis.ref}: no pool liquidity on record for the token; not opened")
                continue
            size = min(exposure, (liquidity * LIQUIDITY_SHARE).quantize(Decimal("0.01")))
            if size < MIN_POSITION_USD:
                refused.append(thesis.ref)
                notes.append(
                    f"{thesis.ref}: the pool (${liquidity:,.0f}) supports only ${size} at "
                    f"{LIQUIDITY_SHARE:.0%} of its depth; not opened"
                )
                continue
        side = OrderSide.BUY if thesis.direction == "up" else OrderSide.SELL
        broker.marks[thesis.instrument] = price
        # One firing's failure is that firing's: a savepoint rolls back its
        # order and nothing else. On 15 September one bad order poisoned the
        # session, the wake, and the service (M45).
        try:
            with session.begin_nested():
                outcome = runtime.cycle.run(
                    session,
                    portfolio_ref=book,
                    broker=broker,
                    intents=((version_ref, thesis.instrument, side, size, price),),
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
                        entry_price=str(price),
                        entry_bar_at=bar_at,
                    )
                )
                session.flush()
        except sa.exc.SQLAlchemyError as error:
            refused.append(thesis.ref)
            notes.append(f"{thesis.ref}: the order failed and was rolled back ({_why(error)})")
            continue
        opened.append(thesis.ref)

    if opened:
        runtime.ledger.append(
            session,
            kind=EventKind.MECHANISM_TRADED,
            actor=actors["executor"],
            subject=mechanism.ref,
            payload={
                "version": version_ref,
                "book": book,
                "opened": len(opened),
                "closed": 0,
                "refused": len(refused),
                "at": isoformat(moment),
            },
            at=moment,
        )
    closing = close_settled(runtime, session, mechanism, at=moment)
    return PaperResult(
        mechanism.ref,
        tuple(opened),
        closing.closed,
        tuple(refused) + closing.refused,
        "; ".join(notes + ([closing.note] if closing.note else [])),
    )


def _executable_price(
    session: Session, instrument: str, at: dt.datetime
) -> tuple[Decimal, dt.datetime] | None:
    """The newest close the company had recorded for ``instrument`` at ``at``.

    From the newest recording of the instrument, the last bar that opened at
    or before the moment. What a trader at the wake could have dealt near;
    the trigger's own close is what they could have dealt near an hour ago.
    """
    from aurelis.intel.snapshots import MarketSnapshot, Snapshots

    snapshot = (
        session.execute(
            sa.select(MarketSnapshot)
            .where(MarketSnapshot.symbol == instrument)
            .order_by(MarketSnapshot.fetched_at.desc(), MarketSnapshot.ref.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if snapshot is None:
        return None
    moment = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    known: tuple[Decimal, dt.datetime] | None = None
    for bar in Snapshots.bars_of(session, snapshot.ref):
        when = bar.timestamp if bar.timestamp.tzinfo else bar.timestamp.replace(tzinfo=dt.UTC)
        if when <= moment and (known is None or when > known[1]):
            known = (Decimal(str(bar.close)), when)
    return known


def _aware(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def has_open_trades(session: Session, mechanism_ref: str) -> bool:
    return (
        session.execute(
            sa.select(sa.func.count()).where(
                MechanismTrade.mechanism_ref == mechanism_ref,
                MechanismTrade.close_order_ref.is_(None),
            )
        ).scalar_one()
        > 0
    )


def close_settled(
    runtime: Any,
    session: Session,
    mechanism: Mechanism,
    *,
    at: dt.datetime | None = None,
) -> PaperResult:
    """Close every open paper position whose prediction has scored.

    Called for *any* mechanism with open trades, scheme or not. A position
    opened while the mechanism was a candidate scheme is closed at its horizon
    even if the record has since demoted the mechanism: the alternative was a
    position nothing would ever close, which is how M39 found this. The close
    is sized by the quantity the opening fill bought, so the book is flat in
    that instrument afterwards (M42).
    """
    moment = at or runtime.clock.now()
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
    if not to_close:
        return PaperResult(mechanism.ref, (), (), (), "")
    actors = _actors(runtime, session)
    version_ref = mechanism.version_ref or ensure_version(runtime, session, mechanism, at=moment)
    broker = runtime.brokers[BrokerKind.PAPER]
    closed: list[str] = []
    refused: list[str] = []
    notes: list[str] = []
    for trade, thesis in to_close:
        # Closed at the newest close the wake can see, not the resolution
        # bar's: the horizon passed, and the order is placed now.
        known = _executable_price(session, thesis.instrument, moment)
        if known is None or (
            trade.entry_bar_at is not None and known[1] <= _aware(trade.entry_bar_at)
        ):
            notes.append(f"{thesis.ref}: no price newer than the entry yet; still open")
            continue
        price, bar_at = known
        side = OrderSide.SELL if thesis.direction == "up" else OrderSide.BUY
        # Sized by what the opening fill bought, at the price it closes at:
        # the same dollar exposure at a different price is a different
        # quantity, and the difference stayed on the book. The first two
        # live round trips left a short of 129 RAY and a long of 1 HYPE.
        opened = _fill(session, trade.open_order_ref)
        if opened is None:
            refused.append(thesis.ref)
            notes.append(f"{thesis.ref}: its opening order has no fill; not closed")
            continue
        held = Decimal(str(opened[1].quantity))
        broker.marks[thesis.instrument] = price
        try:
            with session.begin_nested():
                outcome = runtime.cycle.run(
                    session,
                    portfolio_ref=trade.portfolio_ref,
                    broker=broker,
                    intents=(
                        (version_ref, thesis.instrument, side, _room(held, price), price, held),
                    ),
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
                trade.exit_price = str(price)
                trade.exit_bar_at = bar_at
                trade.pnl = _round_trip_pnl(session, trade.open_order_ref, trade.close_order_ref)
                session.flush()
        except sa.exc.SQLAlchemyError as error:
            session.refresh(trade)
            refused.append(thesis.ref)
            notes.append(f"{thesis.ref}: the close failed and was rolled back ({_why(error)})")
            continue
        closed.append(thesis.ref)
    if closed:
        runtime.ledger.append(
            session,
            kind=EventKind.MECHANISM_TRADED,
            actor=actors["executor"],
            subject=mechanism.ref,
            payload={
                "version": version_ref,
                "book": to_close[0][0].portfolio_ref,
                "opened": 0,
                "closed": len(closed),
                "refused": len(refused),
                "at": isoformat(moment),
            },
            at=moment,
        )
    return PaperResult(mechanism.ref, (), tuple(closed), tuple(refused), "; ".join(notes))


def books_with_trades(session: Session) -> list[str]:
    """Every paper book a mechanism has traded in, by portfolio ref."""
    return sorted(
        {str(ref) for (ref,) in session.execute(sa.select(MechanismTrade.portfolio_ref).distinct())}
    )


def flatten_book(
    runtime: Any, session: Session, portfolio_ref: str, *, at: dt.datetime | None = None
) -> PaperResult:
    """Flatten every position in a mechanism book that no open trade accounts for.

    A residual is a quantity the book holds in an instrument with no open
    mechanism trade in it: what a close sized by exposure rather than by
    quantity left behind (the two before M42), or what a partial fill would
    leave. It is closed at the newest price the wake can see, through the
    same chain as any order, under the version of the mechanism that last
    traded the instrument, and the flattening is on the ledger. A book that
    is flat returns an empty result and writes nothing.
    """
    moment = at or runtime.clock.now()
    open_symbols = {
        str(instrument)
        for (instrument,) in session.execute(
            sa.select(Thesis.instrument)
            .join(MechanismTrade, MechanismTrade.thesis_ref == Thesis.ref)
            .where(
                MechanismTrade.portfolio_ref == portfolio_ref,
                MechanismTrade.close_order_ref.is_(None),
            )
        )
    }
    residuals = [
        p
        for p in runtime.execution.positions(session, portfolio_ref)
        if Decimal(str(p.quantity)) != 0 and p.symbol not in open_symbols
    ]
    if not residuals:
        return PaperResult(portfolio_ref, (), (), (), "")
    actors = _actors(runtime, session)
    broker = runtime.brokers[BrokerKind.PAPER]
    flattened: list[str] = []
    refused: list[str] = []
    notes: list[str] = []
    for position in residuals:
        quantity = Decimal(str(position.quantity))
        known = _executable_price(session, position.symbol, moment)
        if known is None:
            refused.append(position.symbol)
            notes.append(f"{position.symbol}: no recorded price; residual {quantity} stays")
            continue
        price, _ = known
        last = session.execute(
            sa.select(Order.version_ref)
            .where(Order.portfolio_ref == portfolio_ref, Order.symbol == position.symbol)
            .order_by(Order.submitted_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last is None:
            refused.append(position.symbol)
            notes.append(f"{position.symbol}: no order ever placed under a version; residual stays")
            continue
        side = OrderSide.SELL if quantity > 0 else OrderSide.BUY
        broker.marks[position.symbol] = price
        try:
            with session.begin_nested():
                outcome = runtime.cycle.run(
                    session,
                    portfolio_ref=portfolio_ref,
                    broker=broker,
                    intents=(
                        (
                            str(last),
                            position.symbol,
                            side,
                            _room(abs(quantity), price),
                            price,
                            abs(quantity),
                        ),
                    ),
                    proposer=actors["proposer"],
                    assessor=actors["assessor"],
                    approver=actors["approver"],
                    executor=actors["executor"],
                    analyst=actors["analyst"],
                    at=moment,
                )
        except sa.exc.SQLAlchemyError as error:
            refused.append(position.symbol)
            notes.append(
                f"{position.symbol}: the flattening failed and was rolled back ({_why(error)})"
            )
            continue
        if not outcome.orders:
            refused.append(position.symbol)
            notes.append(f"{position.symbol}: the chain refused the flattening order")
            continue
        flattened.append(position.symbol)
        notes.append(f"{position.symbol}: residual {quantity} flattened at {price}")
    if flattened:
        runtime.ledger.append(
            session,
            kind=EventKind.MECHANISM_TRADED,
            actor=actors["executor"],
            subject=portfolio_ref,
            payload={
                "book": portfolio_ref,
                "opened": 0,
                "closed": 0,
                "flattened": flattened,
                "refused": len(refused),
                "at": isoformat(moment),
            },
            at=moment,
        )
    return PaperResult(portfolio_ref, (), tuple(flattened), tuple(refused), "; ".join(notes))


def _why(error: BaseException) -> str:
    """A database error in one line: the rule that refused, not the SQL."""
    return str(getattr(error, "orig", error)).splitlines()[0][:160]


def _liquidity_of(session: Session, instrument: str) -> Decimal | None:
    """The pool liquidity the newest attention event reported for a token."""
    from aurelis.world.tables import WorldEvent

    rows = session.execute(
        sa.select(WorldEvent.payload)
        .where(
            WorldEvent.entity_kind == "instrument",
            WorldEvent.entity_key == instrument,
            WorldEvent.kind.in_(("attention.boost", "dex.trending")),
        )
        .order_by(WorldEvent.at.desc())
        .limit(5)
    ).scalars()
    for payload in rows:
        raw = (payload or {}).get("liquidity_usd") or (payload or {}).get("reserve_usd")
        if raw:
            try:
                value = Decimal(str(raw))
            except ArithmeticError:
                continue
            if value > 0:
                return value
    return None


def _room(quantity: Decimal, price: Decimal) -> Decimal:
    """The exposure to ask Risk for when the order is exactly ``quantity`` units:
    a cent above the notional, so the database's floating-point check that an
    order does not exceed its approval has room to agree that equal is not
    more. The order itself is capped at ``quantity``."""
    return (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_UP) + Decimal("0.01")


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
    # Entry slippage against the trigger's close, in basis points, signed so
    # that positive is worse for the position: a long filled above the
    # reference paid it, a short filled below it did.
    slips: list[Decimal] = []
    for trade in rows:
        if not trade.entry_price:
            continue
        thesis = session.execute(
            sa.select(Thesis.reference_close, Thesis.direction).where(
                Thesis.ref == trade.thesis_ref
            )
        ).first()
        if thesis is None:
            continue
        reference = Decimal(str(thesis[0]))
        if reference <= 0:
            continue
        moved = (Decimal(trade.entry_price) - reference) / reference * 10_000
        slips.append(moved if thesis[1] == "up" else -moved)
    return {
        "trades": len(rows),
        "open": len(rows) - len(closed),
        "closed": len(closed),
        "won": sum(1 for r in closed if Decimal(str(r.pnl or 0)) > 0),
        "pnl": total.quantize(Decimal("0.01")),
        "slippage_bps": (
            (sum(slips, Decimal(0)) / len(slips)).quantize(Decimal("0.1")) if slips else None
        ),
    }
