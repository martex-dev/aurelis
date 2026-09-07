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

__all__ = ["AuthoringAttempt", "Campaign"]


class Campaign(Base):
    """A budget for searching, fixed before the search starts.

    The row exists so that "how many designs did the company let itself try?"
    is answerable from the record rather than from whoever ran it. ``budget``,
    ``declared_width`` and ``criterion`` are frozen by a database trigger once
    the first attempt has run: a budget that could be raised after seeing the
    results is not a budget, it is a description of what happened.

    ``surplus`` is the column the whole milestone turns on. It is the best
    Sharpe the campaign found **minus** what a search of this width returns
    from noise alone, and a campaign whose surplus is negative found nothing --
    expensively. Stored as text like every other exact decimal here, and every
    CHECK on it casts before it compares, because SQLite compares a number to a
    string by type class.
    """

    __tablename__ = "authoring_campaigns"

    campaign_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    budget: Mapped[int] = mapped_column()
    """How many attempts the campaign may make. Declared, then frozen."""

    declared_width: Mapped[int] = mapped_column()
    """How many designs those attempts search between them: the whole space for
    the first, and the one-slot neighbourhood for each revision."""

    criterion: Mapped[str] = mapped_column(sa.Text())
    """What would have counted as a result, written before there was one."""

    plan_digest: Mapped[str] = mapped_column(sa.String(64))
    locked_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))

    attempts_run: Mapped[int] = mapped_column(default=0)
    refusals: Mapped[int] = mapped_column(default=0)
    exhausted: Mapped[bool] = mapped_column(default=False)
    """Whether the budget ran out. A campaign that stopped early stopped for a
    reason the row can name; one that ran to the end says so."""

    best_attempt_ref: Mapped[str | None] = mapped_column(sa.String(24), default=None)
    best_sharpe: Mapped[str | None] = mapped_column(sa.String(32), default=None)
    expected_by_chance: Mapped[str | None] = mapped_column(sa.String(32), default=None)
    surplus: Mapped[str | None] = mapped_column(sa.String(32), default=None)
    survives_selection: Mapped[bool | None] = mapped_column(default=None)

    trials_in_family: Mapped[int] = mapped_column(default=0)
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), default=None
    )

    __table_args__ = (
        sa.CheckConstraint("budget > 0", name="ck_campaign_budget_is_positive"),
        sa.CheckConstraint(
            "declared_width >= budget",
            name="ck_campaign_width_covers_its_attempts",
        ),
        sa.CheckConstraint(
            "attempts_run <= budget", name="ck_campaign_stays_inside_its_budget"
        ),
        sa.CheckConstraint("length(criterion) > 0", name="ck_campaign_states_a_criterion"),
    )


class AuthoringAttempt(Base):
    """One agent's pass through the design space, and where it ended up."""

    __tablename__ = "authoring_attempts"

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    task_ref: Mapped[str | None] = mapped_column(sa.String(24), default=None)

    campaign_ref: Mapped[str | None] = mapped_column(
        sa.String(24), index=True, default=None
    )
    """The campaign this attempt belongs to, or null for a standalone one.
    Nullable rather than defaulted to a synthetic campaign, because "searched
    once" and "searched inside a declared budget" are different facts."""

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
            "declared_cells > 0", name="ck_authoring_declares_something"
        ),
        sa.CheckConstraint(
            "campaign_ref IS NOT NULL OR declared_cells >= space",
            name="ck_standalone_attempt_declares_the_whole_space",
        ),
        # The point of M15, enforced rather than remembered: a standalone
        # attempt may not declare fewer cells than the space the agent chose
        # from. Declaring one cell for a search over seventy-two is how a false
        # discovery becomes arithmetically invisible.
        #
        # The campaign clause is not an exemption. An attempt inside a campaign
        # searched a slot rather than the space, and its budget declared the
        # sum of those before the first design existed -- so the guarantee moves
        # up a level to ck_campaign_width_covers_its_attempts rather than being
        # dropped. Written flat, the constraint was simply wrong: it refused
        # every revision the first time a campaign ran.
    )
