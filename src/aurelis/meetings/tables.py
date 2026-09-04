"""What a meeting leaves behind.

The transcript is kept in full and is a first-class object, not a log line.
Reading why the company believes something is one of the things Mission
Control exists for, so every turn is stored with its speaker, its stance, the
evidence it cited, and whether the speaker changed position.

Three columns do disproportionate work:

``MeetingTurn.stance`` lets the Chair select speakers by genuine disagreement.

``MeetingTurn.changed_mind_from`` records updating on evidence, which is the
behaviour the company most wants and the one hardest to see from prose.

``Decision.dissent`` is a stored field. A decision recording no dissent is one
where nobody disagreed — which is a different fact from one where disagreement
was smoothed away, and the two must not look alike a year later.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.meetings.types import MeetingStatus, ObjectionStatus
from aurelis.platform.db.tables import Base

__all__ = [
    "ActionItem",
    "Decision",
    "Forecast",
    "Meeting",
    "MeetingObjection",
    "MeetingParticipant",
    "MeetingTurn",
]


class Meeting(Base):
    """One convened meeting."""

    __tablename__ = "meetings"

    meeting_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    type: Mapped[str] = mapped_column(sa.String(24), index=True)
    subject: Mapped[str] = mapped_column(sa.String(256))
    trigger: Mapped[str] = mapped_column(sa.Text, default="")

    subject_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    """The mission, project or record this is about."""

    department: Mapped[str | None] = mapped_column(sa.String(48), index=True)
    desk: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    chair: Mapped[str] = mapped_column(sa.String(24), index=True)

    agenda: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    evidence_pack: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    evidence_digest: Mapped[str | None] = mapped_column(sa.String(64))
    """The pack, stored as an artifact. What everyone was shown is citable in
    exactly the same way as any other artifact."""

    budget_tokens: Mapped[int] = mapped_column(default=0)
    budget_rounds: Mapped[int] = mapped_column(default=0)
    max_turn_tokens: Mapped[int] = mapped_column(default=0)

    tokens_spent: Mapped[int] = mapped_column(default=0)
    usd_spent: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    rounds_used: Mapped[int] = mapped_column(default=0)
    budget_exhausted: Mapped[bool] = mapped_column(default=False)
    """Running out of meeting is a normal outcome, not a failure. Recorded so
    a type that keeps exhausting its budget can have it raised."""

    status: Mapped[str] = mapped_column(
        sa.String(16), default=MeetingStatus.SCHEDULED, index=True
    )
    productive: Mapped[bool] = mapped_column(default=False)
    state_changes: Mapped[int] = mapped_column(default=0)
    """Decisions, action items and objections produced. A meeting with none is
    logged unproductive, and that number is a metric on the Chair and on the
    meeting type."""

    minutes_digest: Mapped[str | None] = mapped_column(sa.String(64))
    convened_at: Mapped[dt.datetime] = mapped_column(index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column()

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('scheduled','in_session','synthesising','closed','abandoned')",
            name="ck_meetings_status",
        ),
    )


class MeetingParticipant(Base):
    """Who was in the room, and in what capacity."""

    __tablename__ = "meeting_participants"

    meeting_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("meetings.ref", ondelete="CASCADE"), primary_key=True
    )
    agent_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True, index=True)
    attendance: Mapped[str] = mapped_column(sa.String(16))

    charters_at_the_time: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """What this agent held when it spoke. Coverage moves as the company
    splits its own roles, and a transcript that resolved authority at read
    time would misattribute a two-year-old argument."""

    final_stance: Mapped[str | None] = mapped_column(sa.String(16))


class MeetingTurn(Base):
    """One thing somebody said. Immutable once recorded."""

    __tablename__ = "meeting_turns"

    turn_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    meeting_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    seq: Mapped[int] = mapped_column()
    round: Mapped[int] = mapped_column(default=0)
    phase: Mapped[str] = mapped_column(sa.String(16), index=True)

    speaker: Mapped[str] = mapped_column(sa.String(24), index=True)
    """Scope-guarded: the trigger checks this agent holds MEETING_TURN."""

    addressed_to: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    kind: Mapped[str] = mapped_column(sa.String(16), index=True)
    body: Mapped[str] = mapped_column(sa.Text)

    claims: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    evidence_refs: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    stance: Mapped[str] = mapped_column(sa.String(16), default="uncertain")
    changed_mind_from: Mapped[str | None] = mapped_column(sa.String(16))

    tokens: Mapped[int] = mapped_column(default=0)
    usd: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.UniqueConstraint("meeting_ref", "seq", name="uq_turn_order"),
        sa.Index("ix_turns_meeting_seq", "meeting_ref", "seq"),
    )


class Forecast(Base):
    """A probability recorded before the holder heard anyone.

    The company's cheapest honest quality signal: one low-tier call each,
    scored later against what actually happened, and non-circular in a way no
    amount of one model grading another's prose can be.
    """

    __tablename__ = "forecasts"

    forecast_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    meeting_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    question: Mapped[str] = mapped_column(sa.Text)
    probability: Mapped[Decimal] = mapped_column()
    """In [0, 1], as an exact decimal. A forecast through a binary float would
    not hash reproducibly, and calibration is computed from these."""

    reasoning: Mapped[str] = mapped_column(sa.Text, default="")
    recorded_at: Mapped[dt.datetime] = mapped_column(index=True)

    outcome: Mapped[bool | None] = mapped_column()
    brier: Mapped[Decimal | None] = mapped_column()
    """``(probability - outcome)^2``. Lower is better; 0.25 is what you get by
    always saying 50%."""

    scored_at: Mapped[dt.datetime | None] = mapped_column()
    scored_against: Mapped[str | None] = mapped_column(sa.String(24))

    __table_args__ = (
        sa.CheckConstraint(
            "CAST(probability AS REAL) >= 0 AND CAST(probability AS REAL) <= 1",
            name="ck_forecast_is_a_probability",
        ),
        sa.UniqueConstraint("meeting_ref", "agent_ref", name="uq_one_forecast_each"),
    )


class MeetingObjection(Base):
    """A challenge, with the test that would settle it.

    ``discriminating_test`` is the load-bearing field and the reason debate in
    this company ends in evidence rather than exhaustion. An objection without
    one is recorded as ``UNTESTABLE`` and reported as an unresolved limitation
    — never silently dropped, and never allowed to block indefinitely either.
    """

    __tablename__ = "meeting_objections"

    objection_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    meeting_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    author: Mapped[str] = mapped_column(sa.String(24), index=True)
    target: Mapped[str] = mapped_column(sa.String(64))
    type: Mapped[str] = mapped_column(sa.String(32), index=True)
    severity: Mapped[str] = mapped_column(sa.String(16), index=True)
    statement: Mapped[str] = mapped_column(sa.Text)

    discriminating_test: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    status: Mapped[str] = mapped_column(
        sa.String(16), default=ObjectionStatus.OPEN, index=True
    )
    test_result: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    resolved_at: Mapped[dt.datetime | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(index=True)


class Decision(Base):
    """What was decided, and who disagreed."""

    __tablename__ = "decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    meeting_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    subject: Mapped[str] = mapped_column(sa.String(256))
    outcome: Mapped[str] = mapped_column(sa.Text)
    rationale: Mapped[str] = mapped_column(sa.Text, default="")

    supporting: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    dissent: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """``[{agent, stance, reason, evidence_refs}]``. Permanent."""

    evidence_refs: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    decided_by: Mapped[str] = mapped_column(sa.String(24))
    decided_at: Mapped[dt.datetime] = mapped_column(index=True)
    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64))


class ActionItem(Base):
    """Something a meeting decided somebody would do.

    Every one becomes a real ``Task`` row. An action item that lived only in
    minutes would be a promise nobody could be held to.
    """

    __tablename__ = "action_items"

    item_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    meeting_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    decision_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    description: Mapped[str] = mapped_column(sa.Text)
    owner: Mapped[str] = mapped_column(sa.String(24), index=True)
    task_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    task_kind: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[dt.datetime] = mapped_column()
