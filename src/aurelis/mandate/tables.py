"""The record of the company asking, or declining to ask.

One row per assessment, kept whether the answer was yes or no. The no's are the
point: a company that only recorded the assessment that passed would be unable
to show that the bar had ever held, and the bar holding is the only reason to
believe the yes when it comes.

``standard_digest`` is on every row. The standard is code, so it can be edited —
what it cannot be is edited *quietly*, because a change moves the digest and the
history shows one assessment judged against a different bar than the next.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["MandateAssessment"]


class MandateAssessment(Base):
    """One time the company asked itself whether it was ready."""

    __tablename__ = "mandate_assessments"

    assessment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    standard_digest: Mapped[str] = mapped_column(sa.String(64), index=True)
    """Which bar this was judged against. The guard against a standard lowered
    after it was missed."""

    criteria: Mapped[int] = mapped_column()
    met: Mapped[int] = mapped_column()
    blocked: Mapped[int] = mapped_column()
    """Unmet criteria that no amount of research could satisfy today. Counted
    separately because a to-do list and a result are different things."""

    verdict: Mapped[str] = mapped_column(sa.String(16), index=True)
    """``ready`` or ``not_yet``. There is no third value: a company that could
    report "nearly" would eventually report it about everything."""

    findings: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    """Every criterion with the reading that settled it, kept in full. An
    assessment that stored only its verdict could not be re-argued later."""

    escalated_to: Mapped[str | None] = mapped_column(sa.String(64), default=None)
    """Who was told, when the answer was yes. Null on every not_yet, because
    nobody should be interrupted by a company that decided not to ask."""

    assessed_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.CheckConstraint(
            "verdict IN ('ready', 'not_yet')", name="ck_mandate_verdict_is_binary"
        ),
        sa.CheckConstraint("met <= criteria", name="ck_mandate_met_within_criteria"),
        sa.CheckConstraint(
            "blocked <= criteria - met", name="ck_mandate_blocked_are_unmet"
        ),
        sa.CheckConstraint(
            "verdict <> 'ready' OR met = criteria",
            name="ck_mandate_ready_means_every_criterion",
        ),
        # The last one is the whole milestone in a constraint: the company may
        # not record itself ready while anything it declared in advance is
        # unmet. Enforced by the database rather than by the function that
        # writes the row, because the function is one edit away from being
        # generous with itself.
    )
