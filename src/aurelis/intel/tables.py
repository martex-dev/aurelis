"""Market observations.

The first thing the company produces: something an analyst noticed, with a
timestamp, a source, and a hash of the data it was read from.

**Bitemporal, and that is the whole point.** ``as_of`` is when the fact was
true in the market; ``observed_at`` is when the company learned it. Collapsing
the two is how look-ahead enters through the data layer — a backtest that reads
today's revised figure as though it were available last Tuesday will find edges
that were never there. Two columns, always, and a check constraint that refuses
an observation the company learned *before* it happened.

Observations are facts about what was seen, not conclusions. An interpretation
is a Finding, and Findings arrive at M4 with the research lifecycle.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["MarketObservation", "ObservationKind"]


class ObservationKind(StrEnum):
    """What sort of thing was noticed.

    ``ANOMALY`` is deliberately not ``FINDING``. An anomaly is a lead: it says
    something looks unusual, never that anything has been established. Leads
    that quietly became findings are how a research corpus rots.
    """

    PRICE_STRUCTURE = "price_structure"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    REGIME = "regime"
    DISLOCATION = "dislocation"
    ANOMALY = "anomaly"
    DATA_QUALITY = "data_quality"
    NEWS_EVENT = "news_event"
    SENTIMENT = "sentiment"
    FLOW = "flow"


class MarketObservation(Base):
    """One recorded observation about a market."""

    __tablename__ = "market_observations"

    observation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    author: Mapped[str] = mapped_column(sa.String(24), index=True)
    """Scope-guarded: the trigger checks this agent holds
    WriteScope.MARKET_OBSERVATION through some charter it covers."""

    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    symbol: Mapped[str | None] = mapped_column(sa.String(32), index=True)
    kind: Mapped[str] = mapped_column(sa.String(24), index=True)

    statement: Mapped[str] = mapped_column(sa.Text)
    """What was observed, in words. Interpretation belongs in a Finding."""

    measures: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    """Named quantities, as exact strings. Computed by a tool, never by a
    model — an agent that states a figure it did not receive from a tool
    fails validation."""

    as_of: Mapped[dt.datetime] = mapped_column(index=True)
    """When it was true in the market."""

    observed_at: Mapped[dt.datetime] = mapped_column(index=True)
    """When the company learned it. Never earlier than ``as_of``."""

    source: Mapped[str] = mapped_column(sa.String(48), index=True)
    """Which data source. ``fixture`` is a real, honest value: it says the
    number came from bundled offline data, not a live feed."""

    data_digest: Mapped[str | None] = mapped_column(sa.String(64))
    """Hash of the data this was read from. The provenance anchor."""

    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64))
    task_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "observed_at >= as_of",
            name="ck_observation_not_learned_before_it_happened",
        ),
        sa.Index("ix_observations_desk_asof", "desk", "as_of"),
    )
