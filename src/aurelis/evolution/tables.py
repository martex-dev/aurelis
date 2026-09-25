"""An agent's method: how it forms a view, one version at a time."""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["AgentMethod"]


class AgentMethod(Base):
    """One version of one agent's method.

    ``baseline_views`` and ``baseline_brier`` are the fitness of the method this
    one replaced, measured when it was replaced: the number the new method has
    to beat. ``authored_by`` is the colleague who wrote it, or the agent itself
    when it revised its own. Append-only.
    """

    __tablename__ = "agent_methods"

    method_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    version: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(sa.Text)
    reason: Mapped[str] = mapped_column(sa.Text)
    parent_ref: Mapped[str | None] = mapped_column(sa.String(24))
    authored_by: Mapped[str] = mapped_column(sa.String(24))
    baseline_views: Mapped[int] = mapped_column(default=0)
    baseline_brier: Mapped[str | None] = mapped_column(sa.String(24))
    adopted_at: Mapped[dt.datetime] = mapped_column(index=True)
    digest: Mapped[str] = mapped_column(sa.String(64), unique=True)

    __table_args__ = (
        sa.UniqueConstraint("agent_ref", "version", name="uq_agent_method_version"),
        sa.CheckConstraint("length(text) >= 40", name="ck_agent_method_says_something"),
    )
