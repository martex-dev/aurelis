"""Messages and channels.

Agents genuinely talk to each other, and the record of what they said is a
first-class object rather than a log line. Three properties matter:

**Typed.** A message has a kind, so "who challenged this finding?" is a query.

**Sourced.** ``claims`` and ``evidence_refs`` are carried separately from the
body, so a factual assertion can be checked against what it cites. A body that
asserts a number nothing supports is exactly what the Provenance Officer
exists to catch.

**Scoped.** Posting requires the ``MESSAGE`` write scope, enforced by trigger,
and reading a channel requires membership. An agent that could read any channel
would destroy the information asymmetry the research design depends on.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["Channel", "ChannelKind", "ChannelMember", "Message", "MessageKind"]


class ChannelKind(StrEnum):
    DEPARTMENT = "department"
    DESK = "desk"
    TEAM = "team"
    MISSION = "mission"
    COMPANY = "company"


class MessageKind(StrEnum):
    """The message vocabulary from ``docs/01-architecture.md`` §4.

    Closed, so the timeline stays queryable and the station can render a
    message kind it was never specifically taught about.
    """

    OBSERVATION = "observation"
    BRIEFING = "briefing"
    QUESTION = "question"
    ANSWER = "answer"
    REQUEST = "request"
    PROPOSAL = "proposal"
    CRITIQUE = "critique"
    EVIDENCE = "evidence"
    WARNING = "warning"
    DECISION = "decision"
    ESCALATION = "escalation"
    APPROVAL = "approval"
    REJECTION = "rejection"
    HANDOFF = "handoff"
    MEETING_INVITE = "meeting_invite"
    MEETING_SUMMARY = "meeting_summary"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Channel(Base):
    """A durable place to post.

    One per department, per desk, per team, per mission, plus the company-wide
    channels. Created deterministically from the org registry, so a department
    that exists always has somewhere to talk.
    """

    __tablename__ = "channels"

    channel_id: Mapped[str] = mapped_column(sa.String(48), primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(16), index=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    purpose: Mapped[str] = mapped_column(sa.Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column()


class ChannelMember(Base):
    """Who may read and post in a channel."""

    __tablename__ = "channel_members"

    channel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("channels.channel_id", ondelete="CASCADE"), primary_key=True
    )
    agent_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("agents.ref", ondelete="CASCADE"), primary_key=True, index=True
    )
    joined_at: Mapped[dt.datetime] = mapped_column()


class Message(Base):
    """One thing an agent said."""

    __tablename__ = "messages"

    message_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    from_agent: Mapped[str] = mapped_column(sa.String(24), index=True)
    """Scope-guarded: the trigger checks this agent holds WriteScope.MESSAGE."""

    channel_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("channels.channel_id"), index=True
    )
    to_agents: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)

    kind: Mapped[str] = mapped_column(sa.String(24), index=True)
    priority: Mapped[str] = mapped_column(sa.String(8), default=Priority.NORMAL)

    subject: Mapped[str] = mapped_column(sa.String(256))
    body: Mapped[str] = mapped_column(sa.Text)

    claims: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """Factual assertions, extracted separately from the prose so each can be
    checked against what it cites."""

    evidence_refs: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """Artifact digests and record references supporting the claims."""

    desk: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    mission_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    task_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    requires_response: Mapped[bool] = mapped_column(default=False)
    respond_by: Mapped[dt.datetime | None] = mapped_column()
    thread_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    in_reply_to: Mapped[str | None] = mapped_column(sa.String(24))

    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64))
    """The stored, content-addressed copy of the message body. A message is
    citable in exactly the same way as any other artifact."""

    created_at: Mapped[dt.datetime] = mapped_column(index=True)
