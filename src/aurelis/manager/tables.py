"""A standing directive from the operator, issued through the Manager (M63)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["Directive"]


class Directive(Base):
    """One row per act: a directive issued, or an earlier one revoked.

    ``kind`` is ``issue`` or ``revoke``. An issue carries the directive's text
    and its audience (``["all"]`` or agent handles). A revoke names the ref it
    withdraws in ``revokes``. Append-only, so what the agents were told, and
    for how long, can always be read back. A directive is active from its
    issue until a revoke names it.
    """

    __tablename__ = "directives"

    directive_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    kind: Mapped[str] = mapped_column(sa.String(8))
    text: Mapped[str] = mapped_column(sa.Text, default="")
    audience: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    revokes: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    issued_by: Mapped[str] = mapped_column(sa.String(24))
    """The Manager's agent ref: the operator speaks, the Manager writes it down."""
    because: Mapped[str] = mapped_column(sa.String(24))
    """The chat turn in which the operator asked for it."""
    issued_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint("kind IN ('issue', 'revoke')", name="ck_directive_kind_is_known"),
        sa.CheckConstraint(
            "(kind = 'issue' AND length(text) >= 4 AND revokes IS NULL) "
            "OR (kind = 'revoke' AND revokes IS NOT NULL)",
            name="ck_directive_issue_says_something_revoke_names_one",
        ),
    )
