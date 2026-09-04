"""Missions, projects, and the link from work to the thing it serves.

Three levels, so a company-scale objective decomposes without one giant plan:

.. code-block:: text

    MISSION   "Find durable cross-asset carry premia"
      PROJECT   "Options-desk variance risk premium study"
        TASK      "Measure VRP on SPX 2015-2026 with realistic spreads"

``WorkItem`` is the join from a platform task to the project it belongs to. It
lives here rather than as a column on ``tasks`` because the platform must not
know what a mission is — the queue sequences work for a company that has not
been invented yet.

Progress is **computed from task outcomes, never asserted**. A mission cannot
report itself 67% done; it reports how many of its tasks are finished, how many
failed, and how many were refused for budget. A single percentage that hid the
failures would be the dashboard lying to its reader.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.missions.states import MissionState, ProjectState
from aurelis.platform.db.tables import Base

__all__ = ["Kickoff", "Mission", "Project", "Retrospective", "WorkItem"]


class Mission(Base):
    """A company-scale objective."""

    __tablename__ = "missions"

    mission_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    objective: Mapped[str] = mapped_column(sa.Text)
    scope: Mapped[str] = mapped_column(sa.Text, default="")
    rationale: Mapped[str] = mapped_column(sa.Text, default="")
    priority: Mapped[int] = mapped_column(default=100)

    owner_agent: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    departments: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    desks: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)

    state: Mapped[str] = mapped_column(sa.String(24), default=MissionState.PROPOSED, index=True)

    budget_usd: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    budget_tokens: Mapped[int] = mapped_column(default=0)

    kickoff_ref: Mapped[str | None] = mapped_column(sa.String(24))
    """What satisfied the kickoff gate. ``PLANNING → ACTIVE`` is refused while
    this is null — meeting at the start is a property of the state machine."""

    retrospective_ref: Mapped[str | None] = mapped_column(sa.String(24))
    """Likewise for ``REVIEWING → CLOSED``."""

    deadline: Mapped[dt.datetime | None] = mapped_column()
    opened_at: Mapped[dt.datetime] = mapped_column(index=True)
    activated_at: Mapped[dt.datetime | None] = mapped_column()
    closed_at: Mapped[dt.datetime | None] = mapped_column()
    closure_reason: Mapped[str] = mapped_column(sa.Text, default="")

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('proposed','planning','active','paused','reviewing','closed',"
            "'cancelled','budget_exhausted')",
            name="ck_missions_state",
        ),
    )


class Project(Base):
    """A unit of work inside a mission, owned by one lead."""

    __tablename__ = "projects"

    project_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    mission_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("missions.ref"), index=True
    )

    name: Mapped[str] = mapped_column(sa.String(160))
    intent: Mapped[str] = mapped_column(sa.Text, default="")
    lead_agent: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    desk: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    state: Mapped[str] = mapped_column(sa.String(24), default=ProjectState.PROPOSED, index=True)
    budget_usd: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    budget_tokens: Mapped[int] = mapped_column(default=0)

    kickoff_ref: Mapped[str | None] = mapped_column(sa.String(24))
    retrospective_ref: Mapped[str | None] = mapped_column(sa.String(24))

    opened_at: Mapped[dt.datetime] = mapped_column(index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column()
    closure_reason: Mapped[str] = mapped_column(sa.Text, default="")

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('proposed','planning','active','reviewing','closed',"
            "'cancelled','budget_exhausted')",
            name="ck_projects_state",
        ),
    )


class WorkItem(Base):
    """A platform task, placed in the company's hierarchy.

    Separate from ``tasks`` so the queue stays ignorant of missions. The queue
    sequences work; this says what the work was for.
    """

    __tablename__ = "work_items"

    task_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    mission_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    project_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    step: Mapped[int] = mapped_column(default=0)
    """Position in the project's plan. Ordering for a reader, not a
    constraint — the actual sequencing is task dependencies."""

    created_at: Mapped[dt.datetime] = mapped_column()


class Kickoff(Base):
    """The plan a mission or project starts from.

    At M2 an operator writes it. At M3 a Kickoff *meeting* produces one, and
    ``kind`` records which — so "was this planned by the company or by a human
    in a hurry?" stays answerable years later.
    """

    __tablename__ = "kickoffs"

    kickoff_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    subject_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16))

    plan: Mapped[str] = mapped_column(sa.Text)
    participants: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    authorised_by: Mapped[str] = mapped_column(sa.String(64))
    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[dt.datetime] = mapped_column()


class Retrospective(Base):
    """What was learned. Required before a mission may close.

    At M2 this is an operator record; at M3 a Retrospective meeting produces
    it, and at M6 its lessons flow into institutional memory.
    """

    __tablename__ = "retrospectives"

    retrospective_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    subject_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16))

    summary: Mapped[str] = mapped_column(sa.Text)
    lessons: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    outcome_counts: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    """The task outcomes as they actually were, including the failures. A
    retrospective that recorded only what worked would be the graveyard being
    quietly emptied."""

    authorised_by: Mapped[str] = mapped_column(sa.String(64))
    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[dt.datetime] = mapped_column()
