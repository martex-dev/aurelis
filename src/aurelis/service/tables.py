"""A standing data grant, and one wake of the service.

``data_grants`` is the record of a person saying, once, which vendor and which
instruments the company may fetch on its own. It names who, when and why, and
the trigger in :mod:`aurelis.service.invariants` keeps everything but the
revocation immutable — a grant that could be widened after the fact is a flag,
not a decision.

``service_cycles`` is the heartbeat: one row per wake, saying what was
fetched, what was settled, what the loop did, what it cost, and what broke.
A cycle in which nothing happened is a row too; a service that wrote rows only
on good days would be a service nobody could tell was running.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["DataGrant", "ServiceCycle"]


class DataGrant(Base):
    """A person's standing permission to fetch these instruments from this vendor."""

    __tablename__ = "data_grants"

    grant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    source: Mapped[str] = mapped_column(sa.String(32), index=True)
    """``coinbase``, or ``fixture:<desk>`` for an offline recording."""

    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    instruments: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    interval: Mapped[str] = mapped_column(sa.String(8), default="1h")
    bars: Mapped[int] = mapped_column(default=400)
    """How many bars each fetch records. Enough to cover the longest horizon
    since the last wake with margin; not history, which is a separate fetch."""

    granted_by: Mapped[str] = mapped_column(sa.String(64))
    granted_at: Mapped[dt.datetime] = mapped_column(index=True)
    reason: Mapped[str] = mapped_column(sa.Text)

    rule: Mapped[str | None] = mapped_column(sa.Text)
    """How the instruments were chosen, when they were drawn from the venue's
    own liquidity ranking rather than named one by one. Provenance of the
    decision; the instruments themselves are the decision."""

    selection_digest: Mapped[str | None] = mapped_column(sa.String(64))
    """Artifact digest of the ranking the choice was drawn from."""

    revoked_by: Mapped[str | None] = mapped_column(sa.String(64))
    revoked_at: Mapped[dt.datetime | None] = mapped_column()

    __table_args__ = (
        sa.CheckConstraint("bars > 0", name="ck_grant_bars_positive"),
        sa.CheckConstraint("length(reason) > 10", name="ck_grant_says_why"),
        sa.CheckConstraint("length(granted_by) > 0", name="ck_grant_names_who"),
    )

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    @property
    def is_live(self) -> bool:
        return not self.source.startswith("fixture:")


class ServiceCycle(Base):
    """One wake of the service, whatever it did."""

    __tablename__ = "service_cycles"

    cycle_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    service_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    """Which invocation of the service this wake belongs to."""

    started_at: Mapped[dt.datetime] = mapped_column(index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column()
    next_due_at: Mapped[dt.datetime | None] = mapped_column()

    fetched: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """Snapshot refs recorded this wake."""

    fetch_failures: Mapped[int] = mapped_column(default=0)
    scored: Mapped[int] = mapped_column(default=0)
    pending: Mapped[int] = mapped_column(default=0)
    run_ref: Mapped[str | None] = mapped_column(sa.String(24))
    calls: Mapped[int] = mapped_column(default=0)
    calls_left_today: Mapped[int] = mapped_column(default=0)
    incidents: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """Alert refs raised this wake. Empty is the ordinary case and the row
    still says so."""

    note: Mapped[str] = mapped_column(sa.Text, default="")
