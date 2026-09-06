"""Alerts: what needs a person's attention, and whether anyone gave it.

An alert nobody acknowledged is a different thing from one nobody raised, and
both are different from one that was handled. So the row carries all three
timestamps and the acknowledger's name — an alerting system that only recorded
firing could tell you the company was noisy, but not whether anyone was
listening.

``recommended_action`` is required. An alert that reports a problem without
saying what to do about it hands the whole design task to whoever reads it at
three in the morning, which is the worst available moment to be inventing a
response.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["Alert"]


class Alert(Base):
    """One thing that needs attention."""

    __tablename__ = "alerts"

    alert_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    severity: Mapped[str] = mapped_column(sa.String(16), index=True)
    source: Mapped[str] = mapped_column(sa.String(48), index=True)
    subject: Mapped[str | None] = mapped_column(sa.String(48), index=True)
    desk: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    message: Mapped[str] = mapped_column(sa.Text)
    recommended_action: Mapped[str] = mapped_column(sa.Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)

    raised_by: Mapped[str] = mapped_column(sa.String(24), index=True)
    raised_at: Mapped[dt.datetime] = mapped_column(index=True)

    acknowledged_by: Mapped[str | None] = mapped_column(sa.String(64))
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    resolution: Mapped[str] = mapped_column(sa.Text, default="")

    __table_args__ = (
        sa.CheckConstraint(
            "severity IN ('info','warning','critical')", name="ck_alert_severity"
        ),
        sa.CheckConstraint(
            "length(trim(recommended_action)) > 0",
            name="ck_alert_says_what_to_do",
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL) OR (acknowledged_at IS NOT NULL)",
            name="ck_alert_resolved_only_after_acknowledged",
        ),
    )
