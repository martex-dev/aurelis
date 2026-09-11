"""A mechanism as a row: stated once, hashed, and never quietly changed.

Everything an agent asserts about a mechanism is fixed when it is stated: the
pattern, the direction and horizon of the move it predicts, why it works, who
is on the other side, and the decay model. A mechanism that could be edited
after its predictions came in is a mechanism that can be fitted to its own
results, and the whole design exists to make that impossible.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["Mechanism", "MechanismTrade"]


class Mechanism(Base):
    """A named causal pattern an agent stated over a mined co-occurrence."""

    __tablename__ = "mechanisms"

    mechanism_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    title: Mapped[str] = mapped_column(sa.String(160))

    # ------------------------------------------------ the pattern it fires on
    trigger_kind: Mapped[str] = mapped_column(sa.String(48), index=True)
    """The world-event kind that fires a prediction, e.g. ``price.volume_spike``."""

    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    horizon_hours: Mapped[int] = mapped_column()
    direction: Mapped[str] = mapped_column(sa.String(8))
    confidence: Mapped[Decimal] = mapped_column()
    """What the mechanism predicts, mechanically, on every occurrence."""

    # ------------------------------------------------ why it should work
    why: Mapped[str] = mapped_column(sa.Text)
    other_side: Mapped[str] = mapped_column(sa.Text)
    """Who is on the other side of the trade, and why they take it."""

    decay: Mapped[str] = mapped_column(sa.Text)
    """How crowded it can get and how fast it dies once others find it. A
    mechanism without a decay model is one that will be held too long."""

    # ------------------------------------------------ where it came from
    origin: Mapped[str] = mapped_column(sa.String(24))
    """``invented`` or ``inherited``. What the company created stays
    distinguishable from what it read."""

    found_on_instrument: Mapped[str] = mapped_column(sa.String(32))
    found_on_event: Mapped[str] = mapped_column(sa.String(64))
    """The training occurrence. Its predictions are excluded from the score."""

    model: Mapped[str] = mapped_column(sa.String(64))
    tokens: Mapped[int] = mapped_column(default=0)
    usd: Mapped[Decimal] = mapped_column(default=Decimal("0"))

    stated_at: Mapped[dt.datetime] = mapped_column(index=True)
    seal: Mapped[str] = mapped_column(sa.String(64))
    """SHA-256 over everything above."""

    retired_at: Mapped[dt.datetime | None] = mapped_column()
    retired_reason: Mapped[str] = mapped_column(sa.Text, default="")

    evidence_digest: Mapped[str | None] = mapped_column(sa.String(64))
    """Artifact digest of the in-sample evidence the agent was shown when it
    stated the mechanism. Provenance, outside the seal like the version: it
    records what prompted the claim, not the claim."""

    version_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    """The strategy version this mechanism trades as, once it is a candidate
    scheme. Bookkeeping set after the fact, outside the seal like retirement:
    it changes nothing about what the mechanism claims."""

    __table_args__ = (
        sa.CheckConstraint("direction IN ('up','down')", name="ck_mechanism_direction"),
        sa.CheckConstraint("horizon_hours > 0", name="ck_mechanism_horizon"),
        sa.CheckConstraint(
            "CAST(confidence AS REAL) > 0.5 AND CAST(confidence AS REAL) <= 1",
            name="ck_mechanism_confidence",
        ),
        sa.CheckConstraint("length(why) > 20", name="ck_mechanism_says_why"),
        sa.CheckConstraint("length(decay) > 10", name="ck_mechanism_has_a_decay_model"),
        sa.CheckConstraint("length(other_side) > 10", name="ck_mechanism_names_the_other_side"),
        sa.CheckConstraint("length(seal) = 64", name="ck_mechanism_is_sealed"),
    )


class MechanismTrade(Base):
    """One paper round trip a scheme made on one of its own firings."""

    __tablename__ = "mechanism_trades"

    trade_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    mechanism_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    thesis_ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    portfolio_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    open_order_ref: Mapped[str] = mapped_column(sa.String(24))
    close_order_ref: Mapped[str | None] = mapped_column(sa.String(24))
    opened_at: Mapped[dt.datetime] = mapped_column(index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column()
    pnl: Mapped[Decimal | None] = mapped_column()
    """Realised, after fees, once closed. Reported, never judged: over a short
    window it is mostly luck, and the mandate does not read it."""
