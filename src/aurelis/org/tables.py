"""The org chart, mirrored into the database.

The registry in code is the source of truth. These tables are a **projection**
of it, seeded at ``db init`` and rebuilt whenever the code changes — and they
exist for exactly one reason: so that write scope can be enforced by a database
trigger rather than by application code.

An agent that could write a risk assessment as long as it went around the
runtime would make the separation of duty a diagram. With the charters in
tables, the guard is a ``WHEN NOT EXISTS`` clause on the insert, and it holds
against raw SQL.

Direction of authority, in one line: **code -> tables -> triggers**, never
back. Nothing reads these tables to decide what a charter *is*; they are
consulted only to decide whether a write is allowed.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["CharterReadView", "CharterTool", "CharterWriteScope", "OrgCharter", "OrgDesk"]


class OrgCharter(Base):
    """One role charter. Seeded from :mod:`aurelis.org.charters`."""

    __tablename__ = "org_charters"

    charter_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    number: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(sa.String(128))
    department: Mapped[str] = mapped_column(sa.String(48), index=True)
    remit: Mapped[str] = mapped_column(sa.Text)
    tier: Mapped[str] = mapped_column(sa.String(8))
    seniority: Mapped[str] = mapped_column(sa.String(16))
    desk_specific: Mapped[bool] = mapped_column(default=False)
    deterministic: Mapped[bool] = mapped_column(default=False)


class CharterWriteScope(Base):
    """Which entity kinds a charter may create.

    The load-bearing table. Every scope-guarded insert checks against a join
    through this and :class:`~aurelis.agents.tables.AgentCoverage`.
    """

    __tablename__ = "charter_write_scopes"

    charter_id: Mapped[str] = mapped_column(
        sa.ForeignKey("org_charters.charter_id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(sa.String(48), primary_key=True, index=True)


class CharterReadView(Base):
    """Which views a charter may build."""

    __tablename__ = "charter_read_views"

    charter_id: Mapped[str] = mapped_column(
        sa.ForeignKey("org_charters.charter_id", ondelete="CASCADE"), primary_key=True
    )
    view: Mapped[str] = mapped_column(sa.String(48), primary_key=True, index=True)


class CharterTool(Base):
    """Which capabilities a charter may invoke."""

    __tablename__ = "charter_tools"

    charter_id: Mapped[str] = mapped_column(
        sa.ForeignKey("org_charters.charter_id", ondelete="CASCADE"), primary_key=True
    )
    tool: Mapped[str] = mapped_column(sa.String(48), primary_key=True, index=True)


class OrgDesk(Base):
    """A market desk and whether it is open.

    Status lives in the database rather than only in code because a desk
    genuinely opens and closes at runtime, by Board decision — unlike a
    charter, which is a structural fact about the company.
    """

    __tablename__ = "org_desks"

    desk_id: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[str] = mapped_column(sa.String(16), index=True)
    instruments: Mapped[str] = mapped_column(sa.Text)
    engines: Mapped[str] = mapped_column(sa.Text)
    calendar: Mapped[str] = mapped_column(sa.String(32))
    opens_at_milestone: Mapped[str] = mapped_column(sa.String(8), default="")
    closure_reason: Mapped[str | None] = mapped_column(sa.Text)
