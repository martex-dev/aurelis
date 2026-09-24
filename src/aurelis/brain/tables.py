"""A note in the shared brain: one line somebody left for the whole company."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["BrainNote"]


class BrainNote(Base):
    """A note an agent or the operator added to the shared brain.

    ``author`` is an agent ref or ``operator``. ``topics`` are the instruments,
    event kinds and mechanism refs the note is about, so a seat can show an
    agent the notes on what it is looking at. ``source_ref`` says where it came
    from: the thesis or mechanism the agent was answering when it wrote it, or
    the inbox file the operator dropped. Append-only: a note once read by
    other agents is part of what they were shown, and editing it would change
    their material after the fact.
    """

    __tablename__ = "brain_notes"

    note_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    author: Mapped[str] = mapped_column(sa.String(32), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16), index=True)
    text: Mapped[str] = mapped_column(sa.Text)
    topics: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    source_ref: Mapped[str] = mapped_column(sa.String(200))
    digest: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    written_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint("length(text) >= 12", name="ck_brain_note_says_something"),
    )
