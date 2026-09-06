"""Execution: the only path from an approval to an order.

The chain is proposal → assessment → approval → order → fill → position, and
every link is a foreign key. :meth:`Execution.submit` takes an *approval*, not
an exposure and not a proposal, so there is no argument through which a caller
could execute something Risk did not permit. The database agrees: ``orders``
has a non-nullable FK to ``trade_approvals`` and a trigger that re-checks the
approval is intact at insert time.

Two behaviours worth stating.

**A rejection is recorded, not raised.** A broker refusing an order is
information — about the venue, the instruction, or the price the strategy
assumed — and an exception would throw it away. The order row exists with
``REJECTED`` and its reason.

**Positions are derived from fills, never set.** There is no method that
assigns a quantity. A position is the running consequence of the fills that
produced it, so a book cannot hold something no order created.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger
from aurelis.risk.tables import RiskAssessment, TradeApproval, TradeProposal
from aurelis.trading.brokers import BrokerAdapter, ExecutionRequest
from aurelis.trading.states import OrderSide, OrderStatus
from aurelis.trading.tables import Fill, Order, Position

__all__ = ["Execution", "Executed"]


@dataclass(frozen=True, slots=True)
class Executed:
    """One order and what came back."""

    order: Order
    fill: Fill | None
    position: Position | None

    @property
    def filled(self) -> bool:
        return self.fill is not None

    def describe(self) -> str:
        if self.fill is None:
            return f"{self.order.ref} {self.order.status}: {self.order.rejection_reason}"
        return (
            f"{self.order.ref} filled {self.fill.quantity} {self.order.symbol} "
            f"at {self.fill.price} (expected {self.order.expected_price})"
        )


class Execution:
    """Submits approved orders and keeps the book consistent with its fills."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def submit(
        self,
        session: Session,
        *,
        approval_ref: str,
        broker: BrokerAdapter,
        symbol: str,
        quantity: Decimal,
        expected_price: Decimal,
        submitted_by: str,
        limit_price: Decimal | None = None,
        fee_bps: Decimal = Decimal("10"),
        spread_bps: Decimal = Decimal("5"),
        impact_bps: Decimal = Decimal("0"),
        at: dt.datetime | None = None,
    ) -> Executed:
        """Execute against an approval. There is no other entry point.

        The size is bounded by what Risk allowed, not by the caller: an order
        whose notional exceeds the approval's final target is refused here and
        would be refused by the database anyway.
        """
        moment = at or self._clock.now()
        approval, proposal = self._chain(session, approval_ref)

        if quantity <= 0:
            raise IntegrityViolation("an order must have a positive quantity")

        notional = quantity * expected_price
        if notional > approval.final_target:
            raise IntegrityViolation(
                f"an order of {notional} exceeds the {approval.final_target} "
                f"Risk approved on {approval.proposal_ref}. The approval is the "
                "ceiling, not a suggestion"
            )

        side = OrderSide(proposal.side)
        ref = allocate_ref(session, RefKind.ORDER)
        order = Order(
            order_id=uuid7(),
            ref=ref,
            approval_ref=approval_ref,
            portfolio_ref=proposal.portfolio_ref,
            version_ref=proposal.version_ref,
            desk=proposal.desk,
            broker=broker.kind.value,
            symbol=symbol,
            side=side.value,
            quantity=quantity,
            limit_price=limit_price,
            expected_price=expected_price,
            status=OrderStatus.SUBMITTED,
            submitted_by=submitted_by,
            submitted_at=moment,
        )
        session.add(order)
        session.flush()

        result = broker.submit(
            ExecutionRequest(
                symbol=symbol,
                side=side,
                quantity=quantity,
                expected_price=expected_price,
                fee_bps=fee_bps,
                spread_bps=spread_bps,
                impact_bps=impact_bps,
                limit_price=limit_price,
            ),
            at=moment,
        )

        order.status = result.status.value
        order.rejection_reason = result.rejection_reason or result.detail
        order.settled_at = moment
        session.flush()

        if not result.filled:
            self._ledger.append(
                session,
                kind=EventKind.ORDER_REJECTED,
                actor=submitted_by,
                subject=ref,
                payload={
                    "broker": broker.kind.value,
                    "symbol": symbol,
                    "status": result.status.value,
                    "reason": order.rejection_reason,
                },
                at=moment,
            )
            return Executed(order, None, None)

        fill = Fill(
            fill_id=uuid7(),
            order_ref=ref,
            quantity=result.filled_quantity,
            price=result.price,
            fee=result.fee,
            broker=broker.kind.value,
            venue_detail=result.detail,
            filled_at=moment,
        )
        session.add(fill)
        session.flush()

        position = self._apply(session, proposal.portfolio_ref, symbol, side, fill, moment)

        self._ledger.append(
            session,
            kind=EventKind.ORDER_FILLED,
            actor=submitted_by,
            subject=ref,
            payload={
                "broker": broker.kind.value,
                "symbol": symbol,
                "side": side.value,
                "quantity": str(result.filled_quantity),
                "price": str(result.price),
                "expected_price": str(expected_price),
                "fee": str(result.fee),
                "approval": approval_ref,
            },
            at=moment,
        )
        return Executed(order, fill, position)

    # -------------------------------------------------------- positions

    def _apply(
        self,
        session: Session,
        portfolio_ref: str,
        symbol: str,
        side: OrderSide,
        fill: Fill,
        moment: dt.datetime,
    ) -> Position:
        """Fold one fill into the book.

        Average price moves only when a position grows; reducing one realises
        P&L against the existing average rather than restating it. Restating
        the average on a sell would quietly erase the cost basis the position
        was actually built at.
        """
        position = session.get(Position, (portfolio_ref, symbol))
        if position is None:
            position = Position(
                portfolio_ref=portfolio_ref,
                symbol=symbol,
                quantity=Decimal(0),
                average_price=Decimal(0),
                realised_pnl=Decimal(0),
                fees_paid=Decimal(0),
                opened_at=moment,
                updated_at=moment,
            )
            session.add(position)

        signed = fill.quantity if side is OrderSide.BUY else -fill.quantity
        before = position.quantity
        after = before + signed

        if before == 0 or (before > 0) == (signed > 0):
            total_cost = before * position.average_price + signed * fill.price
            position.average_price = (
                (total_cost / after) if after != 0 else Decimal(0)
            )
        else:
            closed = min(abs(signed), abs(before))
            direction = Decimal(1) if before > 0 else Decimal(-1)
            position.realised_pnl += (
                (fill.price - position.average_price) * closed * direction
            )
            if (after > 0) != (before > 0) and after != 0:
                position.average_price = fill.price

        position.quantity = after
        position.fees_paid += fill.fee
        position.realised_pnl -= fill.fee
        position.updated_at = moment
        position.closed_at = moment if after == 0 else None
        session.flush()
        return position

    def positions(self, session: Session, portfolio_ref: str) -> list[Position]:
        return list(
            session.execute(
                sa.select(Position)
                .where(Position.portfolio_ref == portfolio_ref)
                .order_by(Position.symbol)
            ).scalars()
        )

    def orders(self, session: Session, portfolio_ref: str) -> list[Order]:
        return list(
            session.execute(
                sa.select(Order)
                .where(Order.portfolio_ref == portfolio_ref)
                .order_by(Order.submitted_at)
            ).scalars()
        )

    # ---------------------------------------------------------- helpers

    @staticmethod
    def _chain(
        session: Session, approval_ref: str
    ) -> tuple[TradeApproval, TradeProposal]:
        """Walk approval → assessment → proposal, refusing a broken link."""
        approval = session.execute(
            sa.select(TradeApproval).where(TradeApproval.ref == approval_ref)
        ).scalar_one_or_none()
        if approval is None:
            raise IntegrityViolation(
                f"no approval {approval_ref}; an order requires one and the "
                "database will refuse it regardless of what is passed here"
            )
        assessment = session.execute(
            sa.select(RiskAssessment).where(RiskAssessment.ref == approval.assessment_ref)
        ).scalar_one_or_none()
        if assessment is None:  # pragma: no cover - FK-guarded
            raise IntegrityViolation(
                f"{approval_ref} cites an assessment that does not exist"
            )
        proposal = session.execute(
            sa.select(TradeProposal).where(TradeProposal.ref == approval.proposal_ref)
        ).scalar_one_or_none()
        if proposal is None:  # pragma: no cover - FK-guarded
            raise IntegrityViolation(
                f"{approval_ref} cites a proposal that does not exist"
            )
        return approval, proposal

