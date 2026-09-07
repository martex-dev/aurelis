"""The record of a desk being opened.

A desk's status is not a flag somebody set. It is the outcome of a checklist
evaluated against the running system, and the row below stores what the
checklist said at the moment the desk opened — including the items that were
only **provisional**.

That last part is what the table exists for. Every desk M12 opens runs on
fixture data with no live feed behind it, and there is a strong pull towards
letting that fade into the background once the desk is working. Storing the
caveats on the opening record, and requiring them to be non-empty when there
are any, means a desk cannot quietly graduate from "open on fixtures" to "open"
without somebody writing down what changed.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["DeskOpening"]


class DeskOpening(Base):
    """One desk, opened, with the checklist that let it open."""

    __tablename__ = "desk_openings"

    opening_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    desk: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    """One row per desk. Reopening a desk updates it rather than appending, and
    the ledger carries the history."""

    status: Mapped[str] = mapped_column(sa.String(16), index=True)
    calendar: Mapped[str] = mapped_column(sa.String(16))
    periods_per_year: Mapped[int] = mapped_column()
    """The desk's clock, copied onto the record. Every cross-desk comparison
    divides by this, and a desk whose calendar changed later must not
    retroactively rescale research done before the change."""

    round_trip_cost_bps: Mapped[str] = mapped_column(sa.String(24))
    """Text for exactness, and every comparison on it casts first."""

    material_size_usd: Mapped[str] = mapped_column(sa.String(24))
    max_gross_leverage: Mapped[str] = mapped_column(sa.String(16))
    shortable: Mapped[bool] = mapped_column(default=True)

    checklist: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    caveats: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    """Every provisional item, verbatim. A desk open on fixtures says so here
    and in every report that reads this row."""

    data_is_live: Mapped[bool] = mapped_column(default=False)
    """False on every desk. Kept as a column rather than inferred from the
    caveats, so "is anything here real?" is a query rather than a search
    through prose."""

    opened_by: Mapped[str] = mapped_column(sa.String(24))
    opened_at: Mapped[dt.datetime] = mapped_column(index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column()
    closed_reason: Mapped[str] = mapped_column(sa.Text, default="")

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('proposed','opening','active','dormant','closed')",
            name="ck_desk_opening_status",
        ),
        sa.CheckConstraint(
            "CAST(round_trip_cost_bps AS REAL) > 0",
            name="ck_desk_opening_charges_something",
        ),
        sa.CheckConstraint(
            "CAST(material_size_usd AS REAL) > 0",
            name="ck_desk_opening_has_a_size_ceiling",
        ),
        sa.CheckConstraint("periods_per_year > 0", name="ck_desk_opening_has_a_clock"),
        sa.CheckConstraint(
            "status <> 'closed' OR closed_reason <> ''",
            name="ck_desk_closed_with_a_reason",
        ),
    )
