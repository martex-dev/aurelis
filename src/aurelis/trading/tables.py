"""The execution record: orders, fills, positions, and what reality said.

An ``Order`` cannot exist without an ``approval_ref``. That is a NOT NULL
foreign key *and* a trigger, and together they mean the approval chain is not a
convention the trading code follows but a shape the database will accept. There
is no path from a strategy's desire to an order that does not pass through
Risk.

``GapMeasurement`` is the table this milestone exists for. Every backtest is a
claim about the future; paper trading is the first place that claim meets
something it cannot control. The gap — realised minus expected, per metric — is
the only measurement in the company where reality gets a vote, and it is
tracked as a **company competence** rather than a strategy property: how wrong
our backtests tend to be is a fact about us.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base
from aurelis.trading.states import OrderStatus

__all__ = [
    "Fill",
    "GapMeasurement",
    "Order",
    "Position",
    "PostTradeReport",
]


class Order(Base):
    """An instruction to a broker. Requires an approval, always."""

    __tablename__ = "orders"

    order_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    approval_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("trade_approvals.ref"), index=True
    )
    """Not nullable. An order without an approval is the thing this whole
    layer exists to make impossible."""

    portfolio_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    version_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    desk: Mapped[str] = mapped_column(sa.String(24), index=True)

    broker: Mapped[str] = mapped_column(sa.String(16), index=True)
    symbol: Mapped[str] = mapped_column(sa.String(32), index=True)
    side: Mapped[str] = mapped_column(sa.String(8))
    quantity: Mapped[Decimal] = mapped_column()
    limit_price: Mapped[Decimal | None] = mapped_column()

    expected_price: Mapped[Decimal] = mapped_column()
    """What the strategy assumed it would pay. Recorded before submission so
    slippage is a comparison rather than a reconstruction."""

    status: Mapped[str] = mapped_column(
        sa.String(24), default=OrderStatus.SUBMITTED, index=True
    )
    rejection_reason: Mapped[str] = mapped_column(sa.Text, default="")

    submitted_by: Mapped[str] = mapped_column(sa.String(24), index=True)
    submitted_at: Mapped[dt.datetime] = mapped_column(index=True)
    settled_at: Mapped[dt.datetime | None] = mapped_column()

    __table_args__ = (
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_order_side"),
        sa.CheckConstraint(
            "CAST(quantity AS REAL) > 0", name="ck_order_quantity_positive"
        ),
        sa.CheckConstraint(
            "broker IN ('backtest','simulation','paper')",
            name="ck_order_has_no_live_broker",
        ),
        sa.CheckConstraint(
            "status IN ('submitted','filled','partially_filled','rejected',"
            "'cancelled','expired')",
            name="ck_order_status",
        ),
    )


class Fill(Base):
    """What actually happened. Append-only."""

    __tablename__ = "fills"

    fill_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    order_ref: Mapped[str] = mapped_column(sa.ForeignKey("orders.ref"), index=True)

    quantity: Mapped[Decimal] = mapped_column()
    price: Mapped[Decimal] = mapped_column()
    fee: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    broker: Mapped[str] = mapped_column(sa.String(16))
    venue_detail: Mapped[str] = mapped_column(sa.Text, default="")
    filled_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "CAST(quantity AS REAL) > 0", name="ck_fill_quantity_positive"
        ),
        sa.CheckConstraint(
            "CAST(price AS REAL) > 0", name="ck_fill_price_positive"
        ),
    )


class Position(Base):
    """What the book currently holds, per portfolio and symbol."""

    __tablename__ = "positions"

    portfolio_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    symbol: Mapped[str] = mapped_column(sa.String(32), primary_key=True)

    quantity: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    average_price: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    realised_pnl: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    fees_paid: Mapped[Decimal] = mapped_column(default=Decimal("0"))

    opened_at: Mapped[dt.datetime] = mapped_column()
    updated_at: Mapped[dt.datetime] = mapped_column(index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column()


class PostTradeReport(Base):
    """One order, examined after the fact.

    Slippage is split from fees deliberately. "The costs were higher than
    modelled" and "we were filled at a worse price than modelled" are different
    failures with different fixes, and a single cost number hides which one
    happened.
    """

    __tablename__ = "post_trade_reports"

    report_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    order_ref: Mapped[str] = mapped_column(sa.ForeignKey("orders.ref"), index=True)
    version_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    expected_price: Mapped[Decimal] = mapped_column()
    fill_price: Mapped[Decimal] = mapped_column()
    slippage: Mapped[Decimal] = mapped_column()
    slippage_bps: Mapped[Decimal] = mapped_column()
    fees: Mapped[Decimal] = mapped_column(default=Decimal("0"))

    modelled_cost_bps: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    realised_cost_bps: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    cost_surprise_bps: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    """Realised minus modelled. Positive means the strategy's cost model was
    optimistic, which is the direction that matters."""

    notes: Mapped[str] = mapped_column(sa.Text, default="")
    analysed_by: Mapped[str] = mapped_column(sa.String(24))
    analysed_at: Mapped[dt.datetime] = mapped_column(index=True)


class GapMeasurement(Base):
    """Backtest expectation against what paper trading actually produced.

    The most valuable row in the system, because it is the only one where the
    company's own claim is checked by something it does not control.

    ``expected`` is copied from the run that supported the promotion, with its
    artifact digest, so the comparison cites the exact number that was claimed
    rather than a re-derivation of it.
    """

    __tablename__ = "gap_measurements"

    measurement_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    portfolio_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    desk: Mapped[str] = mapped_column(sa.String(24), index=True)

    metric: Mapped[str] = mapped_column(sa.String(48), index=True)
    expected: Mapped[Decimal] = mapped_column()
    realised: Mapped[Decimal] = mapped_column()
    gap: Mapped[Decimal] = mapped_column()
    """``realised - expected``. Negative means paper did worse than the
    backtest promised, which is the usual direction and the one worth
    forecasting."""

    period_start: Mapped[dt.datetime] = mapped_column(index=True)
    period_end: Mapped[dt.datetime] = mapped_column(index=True)
    observations: Mapped[int] = mapped_column(default=0)

    expected_source: Mapped[str] = mapped_column(sa.String(64))
    """The run or artifact the expectation was read from."""

    realised_source: Mapped[str] = mapped_column(sa.String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    measured_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.UniqueConstraint(
            "version_ref", "metric", "period_end", name="uq_one_gap_per_period"
        ),
    )
