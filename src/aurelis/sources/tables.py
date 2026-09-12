"""A source request: an agent said which feed the company should read, and why."""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["SourceRequest"]


class SourceRequest(Base):
    """One agent's answer about one source, on one catalogue.

    ``wanted`` false is a decline, kept for the same reason a declined
    mechanism is kept: a record of what the company chose not to read, and
    why, is part of what it knows. The catalogue digest says what the agent
    was shown, so a new source in the catalogue is a new question.
    """

    __tablename__ = "source_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    source: Mapped[str] = mapped_column(sa.String(48), index=True)
    wanted: Mapped[bool] = mapped_column()
    reason: Mapped[str] = mapped_column(sa.Text)
    catalogue_digest: Mapped[str] = mapped_column(sa.String(64))
    requested_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (sa.CheckConstraint("length(reason) > 10", name="ck_source_request_says_why"),)
