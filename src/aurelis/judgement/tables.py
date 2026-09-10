"""A thesis as a row: sealed once, scored once, never edited.

The shape of the table is the argument. Everything above ``outcome`` is fixed
at sealing and hashed into ``seal``; everything from ``outcome`` down is
written exactly once, by the resolver, against a named recording. A trigger
refuses any other change (:mod:`aurelis.judgement.invariants`), so the
statement "this was predicted before it happened" is enforced by the database
rather than by whoever remembers to be careful.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["Thesis"]


class Thesis(Base):
    """One judgement, on the record, in advance."""

    __tablename__ = "theses"

    thesis_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    # ------------------------------------------------ what the agent chose
    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    instrument: Mapped[str] = mapped_column(sa.String(32), index=True)
    interval: Mapped[str] = mapped_column(sa.String(8))
    horizon_hours: Mapped[int] = mapped_column()

    # ------------------------------------------------ what it was made against
    snapshot_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    """The recording the reference close came from. What the agent saw."""

    reference_at: Mapped[dt.datetime] = mapped_column()
    """Open time of the last bar the agent was shown."""

    reference_close: Mapped[str] = mapped_column(sa.String(32))
    """Text, for exactness. The proposition is settled against this."""

    resolves_at: Mapped[dt.datetime] = mapped_column(index=True)
    """``reference_at + horizon``. The bar opening here settles it."""

    is_live: Mapped[bool] = mapped_column(default=True)
    """Whether the recording came from a market. A thesis about a fixture is
    a thesis about a fixture, and the calibration report keeps it apart."""

    # ------------------------------------------------ the judgement
    direction: Mapped[str] = mapped_column(sa.String(8))
    confidence: Mapped[Decimal] = mapped_column()
    """In (0.5, 1]. What the agent said, in its own terms."""

    probability_up: Mapped[Decimal] = mapped_column()
    """The same view as a probability that the close at the horizon is above
    the reference. ``confidence`` if the direction is up, ``1 - confidence``
    if down. This is what the Brier score is computed on."""

    thesis: Mapped[str] = mapped_column(sa.Text)
    """Why, in the agent's own words. Figure-checked against the material."""

    wrong_if: Mapped[str] = mapped_column(sa.Text)
    """What would make it wrong, stated before it could be."""

    material_digest: Mapped[str] = mapped_column(sa.String(64))
    """Artifact digest of exactly what the agent was shown."""

    model: Mapped[str] = mapped_column(sa.String(64))
    """Which model answered, or ``stand-in``. Never blank: a judgement whose
    author is unknown cannot be given more or less budget on its record."""

    tokens: Mapped[int] = mapped_column(default=0)
    usd: Mapped[Decimal] = mapped_column(default=Decimal("0"))

    # ------------------------------------------------ the attack, if any
    critic_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    """Who attacked the view before it was sealed. Null means nobody could:
    no agent holding the critic charter was available, and the row says so."""

    attack_verdict: Mapped[str | None] = mapped_column(sa.String(16))
    """``stands``, ``weakened``, ``broken``, or ``unreadable`` when the critic
    answered in a form the seat could not use."""

    attack: Mapped[str | None] = mapped_column(sa.Text)
    confidence_stated: Mapped[Decimal | None] = mapped_column()
    """What the author said before the attack. ``confidence`` is after."""

    response: Mapped[str | None] = mapped_column(sa.String(16))
    """``hold`` or ``revise``. A withdrawal never becomes a row."""

    response_because: Mapped[str | None] = mapped_column(sa.Text)

    # ------------------------------------------------ mechanism predictions
    mechanism_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    """Set when this thesis is a mechanism firing rather than an agent's view.
    The mechanism's out-of-sample record is read from these."""

    mechanism_training: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    """Whether this is the occurrence the mechanism was found on. Excluded from
    the score: a mechanism scored on the instance that suggested it is circular.

    A server default of false so the additive migration can add it to a table
    that already holds views -- every existing thesis is a judgement, not a
    mechanism firing, so false is what those rows mean."""

    mechanism_prediction_key: Mapped[str | None] = mapped_column(
        sa.String(64), unique=True, index=True
    )
    """Hash of (mechanism, trigger event), so one occurrence seals one
    prediction and re-running generation seals nothing new."""

    sealed_at: Mapped[dt.datetime] = mapped_column(index=True)
    seal: Mapped[str] = mapped_column(sa.String(64))
    """SHA-256 over every field above. Recomputed by :func:`verify_seal`."""

    # ------------------------------------------------ written once, later
    outcome: Mapped[bool | None] = mapped_column()
    resolution_at: Mapped[dt.datetime | None] = mapped_column()
    resolution_close: Mapped[str | None] = mapped_column(sa.String(32))
    brier: Mapped[Decimal | None] = mapped_column()
    scored_at: Mapped[dt.datetime | None] = mapped_column()
    scored_against: Mapped[str | None] = mapped_column(sa.String(24))
    """The snapshot the resolving bar was read from."""

    __table_args__ = (
        sa.CheckConstraint("direction IN ('up','down')", name="ck_thesis_direction"),
        sa.CheckConstraint("horizon_hours > 0", name="ck_thesis_horizon_positive"),
        # Money-typed columns are text; compare by value, not by type class.
        sa.CheckConstraint(
            "CAST(confidence AS REAL) > 0.5 AND CAST(confidence AS REAL) <= 1",
            name="ck_thesis_confidence_is_a_view",
        ),
        sa.CheckConstraint(
            "CAST(probability_up AS REAL) >= 0 AND CAST(probability_up AS REAL) <= 1",
            name="ck_thesis_probability",
        ),
        sa.CheckConstraint("length(seal) = 64", name="ck_thesis_is_sealed"),
        sa.CheckConstraint("length(thesis) > 20", name="ck_thesis_has_a_thesis"),
        sa.CheckConstraint("length(wrong_if) > 10", name="ck_thesis_names_a_falsifier"),
        sa.CheckConstraint("resolves_at > sealed_at", name="ck_thesis_is_forward"),
        sa.CheckConstraint(
            "attack_verdict IS NULL OR attack_verdict IN "
            "('stands','weakened','broken','unreadable')",
            name="ck_thesis_attack_verdict",
        ),
        sa.CheckConstraint(
            "response IS NULL OR response IN ('hold','revise')", name="ck_thesis_response"
        ),
    )
