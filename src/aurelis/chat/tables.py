"""One line of a conversation between the operator and an agent (M62)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["ChatTurn"]


class ChatTurn(Base):
    """Something the operator said to an agent, or the agent's answer.

    ``agent_ref`` is the agent the conversation is with, whoever is speaking;
    ``speaker`` is ``operator`` or ``agent``. ``unsourced`` lists the figures
    in an agent's answer that were not in what it was shown. They are kept and
    shown beside the answer rather than refused, because a conversation that
    goes silent whenever a number is rounded is no use to the person in it.
    Append-only, like the rest of the record: what an agent told the operator
    is evidence about the agent.
    """

    __tablename__ = "chat_turns"

    turn_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    speaker: Mapped[str] = mapped_column(sa.String(8))
    text: Mapped[str] = mapped_column(sa.Text)
    in_reply_to: Mapped[str | None] = mapped_column(sa.String(24))
    model: Mapped[str | None] = mapped_column(sa.String(64))
    unsourced: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    said_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint("speaker IN ('operator', 'agent')", name="ck_chat_speaker_is_known"),
        sa.CheckConstraint("length(text) >= 1", name="ck_chat_says_something"),
        sa.CheckConstraint(
            "speaker = 'operator' OR in_reply_to IS NOT NULL",
            name="ck_chat_an_answer_answers_something",
        ),
    )
