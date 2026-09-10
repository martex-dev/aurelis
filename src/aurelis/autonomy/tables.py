"""One row per turn the company took on its own initiative.

Separate from the task queue on purpose. A task is work somebody assigned; an
autonomy cycle is the company deciding what to assign, and the two answer
different questions in an audit. "Who told it to do this?" has an answer here
that is not a person.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["AutonomyCycle"]


class AutonomyCycle(Base):
    """What the company chose to do, why, and what moved."""

    __tablename__ = "autonomy_cycles"

    cycle_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    """The run this cycle belonged to. A run is one invocation; a cycle is one
    decision inside it."""

    n: Mapped[int] = mapped_column()

    unmet: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """What the mandate said was missing when the choice was made. Recorded
    because the choice is only defensible against the state that produced it."""

    action: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    """Null when the cycle decided not to act. That is a real outcome and the
    most common one at the end of a run."""

    reason: Mapped[str] = mapped_column(sa.Text)
    """Why this action, or why none. The sentence an operator reads."""

    outcome: Mapped[str] = mapped_column(sa.String(24), index=True)
    moved: Mapped[bool] = mapped_column(default=False)
    """Whether the condition it aimed at actually changed. An action that ran
    cleanly and moved nothing is the ordinary case here, and conflating it with
    success would make a loop that achieves nothing look busy."""

    detail: Mapped[str] = mapped_column(sa.Text, default="")
    calls: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[dt.datetime] = mapped_column(index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column()

    __table_args__ = (
        sa.CheckConstraint(
            "outcome IN ('acted','refused','failed','stopped')",
            name="ck_autonomy_outcome",
        ),
        sa.CheckConstraint(
            "action IS NOT NULL OR outcome = 'stopped'",
            name="ck_autonomy_no_action_means_stopped",
        ),
        sa.CheckConstraint("length(reason) > 20", name="ck_autonomy_reason_is_real"),
        sa.UniqueConstraint("run_ref", "n", name="uq_autonomy_cycle_number"),
    )
