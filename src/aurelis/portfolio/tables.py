"""The book: allocations and what they add up to.

Split from ``risk`` because the two answer different questions and must be able
to disagree. Portfolio construction says *what we would like to hold*; Risk says
*what is permitted*. Collapsing them into one module would make it natural to
collapse them into one decision, and the whole point of `CLAUDE.md` §12 is that
the agent that wants the exposure is not the agent that approves it.

``Portfolio.mode`` has three values and none of them is ``live``. The CHECK is
the schema-level half of ADR-0006: adding real money is a migration and a
review, not a configuration change.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base
from aurelis.strategy.states import PortfolioMode

__all__ = ["Allocation", "ExposureSnapshot", "Portfolio"]


class Portfolio(Base):
    """A book. Never live."""

    __tablename__ = "portfolios"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    name: Mapped[str] = mapped_column(sa.String(120))
    desks: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    mode: Mapped[str] = mapped_column(
        sa.String(16), default=PortfolioMode.BACKTEST, index=True
    )
    base_currency: Mapped[str] = mapped_column(sa.String(8), default="USD")
    initial_equity: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    constraints: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)

    opened_by: Mapped[str] = mapped_column(sa.String(24))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "mode IN ('backtest','simulation','paper')",
            name="ck_portfolio_has_no_live_mode",
        ),
    )


class Allocation(Base):
    """How much of the book one strategy version is given, and who decided.

    ``decided_by_meeting`` is how an allocation is traceable to an argument.
    A weight nobody can attribute to a decision is a number somebody typed.
    """

    __tablename__ = "allocations"

    allocation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    portfolio_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    version_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    weight: Mapped[Decimal] = mapped_column()
    capacity: Mapped[Decimal | None] = mapped_column()
    rationale: Mapped[str] = mapped_column(sa.Text)
    decided_by_meeting: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    decided_by: Mapped[str] = mapped_column(sa.String(24))
    decided_at: Mapped[dt.datetime] = mapped_column(index=True)
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    withdrawn_reason: Mapped[str] = mapped_column(sa.Text, default="")

    __table_args__ = (
        sa.CheckConstraint(
            "CAST(weight AS REAL) >= 0",
            name="ck_allocation_weight_not_negative",
        ),
        sa.CheckConstraint(
            "length(trim(rationale)) > 0", name="ck_allocation_states_its_reason"
        ),
    )


class ExposureSnapshot(Base):
    """What the book looked like at a moment, including its correlations."""

    __tablename__ = "exposure_snapshots"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    portfolio_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    gross: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    net: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    by_desk: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    concentration: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    """Largest single weight. The simplest concentration measure, and the one
    that catches the failure organisations actually have."""

    correlation: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    correlation_digest: Mapped[str] = mapped_column(sa.String(64), default="")
    """Hash of the matrix, so a gate C evaluation can cite the exact
    correlations it was decided against rather than today's."""

    members: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    taken_at: Mapped[dt.datetime] = mapped_column(index=True)
