"""A decision to follow, or stop following, one account or channel."""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["SocialTarget"]


class SocialTarget(Base):
    """One follow or drop of one handle on one platform. Append-only.

    ``on_instrument`` names the instrument the handle is about, when it is
    about one: a token's own Telegram channel lands every post on that token.
    Without it, a post lands on whichever followed instruments its text names.
    """

    __tablename__ = "social_targets"

    target_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    platform: Mapped[str] = mapped_column(sa.String(16), index=True)
    handle: Mapped[str] = mapped_column(sa.String(160), index=True)
    on_instrument: Mapped[str | None] = mapped_column(sa.String(96))
    followed: Mapped[bool] = mapped_column()
    reason: Mapped[str] = mapped_column(sa.Text)
    decided_by: Mapped[str] = mapped_column(sa.String(24))
    decided_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "platform IN ('telegram', 'x', 'discord')", name="ck_social_target_platform"
        ),
        sa.CheckConstraint("length(reason) >= 8", name="ck_social_target_has_a_reason"),
    )
