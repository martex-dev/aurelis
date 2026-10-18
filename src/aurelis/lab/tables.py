"""The strategy lab's record: each run, and every strategy it tested (M65)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["LabResult", "LabRun"]


class LabRun(Base):
    """One pass of the whole catalogue over the whole universe."""

    __tablename__ = "lab_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    series: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """``[{symbol, desk, source, bars, digest}]``: exactly what was tested on."""
    failed: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """Series that could not be fetched, and why."""
    tests: Mapped[int] = mapped_column()
    luck_trials: Mapped[int] = mapped_column()
    survivors: Mapped[int] = mapped_column()
    ran_at: Mapped[dt.datetime] = mapped_column(index=True)


class LabResult(Base):
    """One strategy on one market, in sample and out, after costs."""

    __tablename__ = "lab_results"

    result_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    strategy: Mapped[str] = mapped_column(sa.String(96), index=True)
    family: Mapped[str] = mapped_column(sa.String(32), index=True)
    symbol: Mapped[str] = mapped_column(sa.String(32), index=True)
    desk: Mapped[str] = mapped_column(sa.String(16), index=True)
    bars: Mapped[int] = mapped_column()
    is_sharpe: Mapped[float] = mapped_column()
    is_return: Mapped[float] = mapped_column()
    oos_sharpe: Mapped[float] = mapped_column()
    oos_return: Mapped[float] = mapped_column()
    oos_hold: Mapped[float] = mapped_column()
    oos_drawdown: Mapped[float] = mapped_column()
    oos_trades: Mapped[int] = mapped_column()
    verdict: Mapped[str] = mapped_column(sa.String(32), index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "verdict IN ('survived', 'failed out of sample', 'no better than luck')",
            name="ck_lab_verdict_is_known",
        ),
    )
