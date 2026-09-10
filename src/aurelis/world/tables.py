"""Entities, events and relations as rows."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["Entity", "Relation", "WorldEvent"]


class Entity(Base):
    """A thing with an identity: an instrument, an asset, a venue, later a
    wallet, an account, a community."""

    __tablename__ = "entities"

    entity_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(32), index=True)
    key: Mapped[str] = mapped_column(sa.String(96), index=True)
    """Stable within its kind: ``BTC-USD`` for an instrument, ``BTC`` for an
    asset, ``coinbase`` for a venue."""

    name: Mapped[str] = mapped_column(sa.String(120), default="")
    attributes: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    """The current state. Every change to it is also an event, so the history
    is in the stream and this is only the latest reading."""

    source: Mapped[str] = mapped_column(sa.String(48), default="")
    first_seen_at: Mapped[dt.datetime] = mapped_column(index=True)
    last_seen_at: Mapped[dt.datetime] = mapped_column()

    __table_args__ = (sa.UniqueConstraint("kind", "key", name="uq_entity_kind_key"),)


class WorldEvent(Base):
    """One typed, timestamped, immutable thing that happened to an entity."""

    __tablename__ = "world_events"

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(48), index=True)
    """``listing.seen``, ``listing.status_changed``, ``price.volume_spike``,
    ``price.range_break``. Dotted by family; a closed vocabulary per source."""

    at: Mapped[dt.datetime] = mapped_column(index=True)
    """When it happened in the world, as best the source knows."""

    recorded_at: Mapped[dt.datetime] = mapped_column(index=True)
    """When the company learned it. Bitemporal, on purpose: a research
    question is asked as of what the company knew, not as of what was true."""

    entity_kind: Mapped[str] = mapped_column(sa.String(32), index=True)
    entity_key: Mapped[str] = mapped_column(sa.String(96), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    source: Mapped[str] = mapped_column(sa.String(96))
    """A vendor endpoint, or ``derived:<snapshot ref>``."""

    digest: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    """Over kind, at, entity and payload. The same fact learned twice is one
    event, and a recording that changed under re-fetch is a new one."""


class Relation(Base):
    """A typed edge between two entities, with a source."""

    __tablename__ = "relations"

    relation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    subject_kind: Mapped[str] = mapped_column(sa.String(32), index=True)
    subject_key: Mapped[str] = mapped_column(sa.String(96), index=True)
    kind: Mapped[str] = mapped_column(sa.String(48), index=True)
    object_kind: Mapped[str] = mapped_column(sa.String(32), index=True)
    object_key: Mapped[str] = mapped_column(sa.String(96), index=True)
    source: Mapped[str] = mapped_column(sa.String(96))
    recorded_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.UniqueConstraint(
            "subject_kind", "subject_key", "kind", "object_kind", "object_key", name="uq_relation"
        ),
    )
