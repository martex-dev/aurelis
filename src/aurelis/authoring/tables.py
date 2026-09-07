"""The record of what the company tried to create, and what happened.

One row per authoring attempt, whatever the verdict. That is the point of the
table: a company that recorded only the attempts that worked would be unable to
answer the one question its own charter says it must be able to answer —
*is it actually inventing anything, or does it just look that way?*

``space`` is the column that stops this being a scoreboard. It records how many
designs the agent chose between, so a row that reads ``CONFIRMED`` can be read
next to the size of the search that produced it. An attempt table without it
would let a hundred attempts and one success read exactly like one attempt and
one success.

``beat_baselines`` is stored as a nullable boolean and is **not** the verdict.
The verdict comes from criteria locked before the run; the baseline comparison
is computed afterwards, against references that were never registered as
claims. Keeping them in separate columns keeps the difference legible: one is
what the company promised to test, the other is context.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["AuthoringAttempt"]


class AuthoringAttempt(Base):
    """One agent's pass through the design space, and where it ended up."""

    __tablename__ = "authoring_attempts"

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    task_ref: Mapped[str | None] = mapped_column(sa.String(24), default=None)

    design: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    design_digest: Mapped[str] = mapped_column(sa.String(64), index=True)
    space: Mapped[int] = mapped_column()
    """How many designs were reachable. The denominator, on the row."""

    origin: Mapped[str] = mapped_column(sa.String(32))
    origin_ref: Mapped[str] = mapped_column(sa.String(24))

    strategy_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    version_ref: Mapped[str] = mapped_column(sa.String(24), unique=True)
    spec_digest: Mapped[str] = mapped_column(sa.String(64))

    hypothesis_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    registration_ref: Mapped[str] = mapped_column(sa.String(24))
    run_ref: Mapped[str] = mapped_column(sa.String(24))
    verdict: Mapped[str] = mapped_column(sa.String(24), index=True)

    declared_cells: Mapped[int] = mapped_column()
    trials_in_family: Mapped[int] = mapped_column()
    """Everything ever locked in this family, this attempt included. What a
    later deflation would have to divide by."""

    metrics: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    baselines: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    beat_baselines: Mapped[bool | None] = mapped_column(default=None)

    refused_at: Mapped[str | None] = mapped_column(sa.String(32), default=None)
    """The slot an authoring failed on, when one did. Null on a completed
    attempt, and never the same column as a verdict: a refusal is the agent
    failing to answer, not the market failing to cooperate."""

    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.CheckConstraint("space > 0", name="ck_authoring_space_is_positive"),
        sa.CheckConstraint(
            "declared_cells >= space",
            name="ck_authoring_declares_the_whole_space",
        ),
        # The whole point of the milestone, enforced rather than remembered:
        # an attempt may not declare fewer cells than the space the agent
        # chose from. Declaring one cell for a search over seventy-two is how
        # a false discovery becomes arithmetically invisible.
    )
