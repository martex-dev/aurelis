"""Writing to and querying the world model."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import sha256_of
from aurelis.core.clock import Clock, SystemClock, isoformat
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import uuid7
from aurelis.platform.ledger.ledger import Ledger
from aurelis.world.tables import Entity, Relation, WorldEvent

__all__ = ["CoOccurrence", "World"]


@dataclass(frozen=True, slots=True)
class CoOccurrence:
    """Two kinds of event on the same entity inside a window."""

    entity_kind: str
    entity_key: str
    first: WorldEvent
    second: WorldEvent

    @property
    def gap(self) -> dt.timedelta:
        return self.second.at - self.first.at


class World:
    """Entities, events and relations. Every write is a fact with a source."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # ---------------------------------------------------------------- entities

    def see(
        self,
        session: Session,
        *,
        kind: str,
        key: str,
        name: str = "",
        attributes: dict[str, Any] | None = None,
        source: str = "",
        at: dt.datetime | None = None,
    ) -> tuple[Entity, bool]:
        """Record that an entity exists, or that it was seen again.

        Returns the row and whether it was new. A change in attributes is
        applied here and is the caller's job to record as an event as well;
        :func:`aurelis.world.sources.sync_catalogue` does exactly that.
        """
        moment = at or self._clock.now()
        row = session.execute(
            sa.select(Entity).where(Entity.kind == kind, Entity.key == key)
        ).scalar_one_or_none()
        if row is None:
            row = Entity(
                entity_id=uuid7(),
                kind=kind,
                key=key,
                name=name or key,
                attributes=dict(attributes or {}),
                source=source,
                first_seen_at=moment,
                last_seen_at=moment,
            )
            session.add(row)
            session.flush()
            return row, True
        row.last_seen_at = moment
        if attributes is not None:
            row.attributes = dict(attributes)
        if name:
            row.name = name
        session.flush()
        return row, False

    @staticmethod
    def entity(session: Session, kind: str, key: str) -> Entity | None:
        return session.execute(
            sa.select(Entity).where(Entity.kind == kind, Entity.key == key)
        ).scalar_one_or_none()

    # ---------------------------------------------------------------- events

    def record(
        self,
        session: Session,
        *,
        kind: str,
        at: dt.datetime,
        entity_kind: str,
        entity_key: str,
        payload: dict[str, Any],
        source: str,
        recorded_at: dt.datetime | None = None,
    ) -> tuple[WorldEvent, bool]:
        """Append one event, or return the identical one already recorded.

        The digest is over what happened, not when it was learned, so the
        same fact from two fetches is one event -- and a fact that differs by
        one field is a different event, which is what a status change is.
        """
        moment = recorded_at or self._clock.now()
        digest = sha256_of(
            {
                "kind": kind,
                "at": isoformat(at),
                "entity": [entity_kind, entity_key],
                "payload": payload,
            }
        )
        existing = session.execute(
            sa.select(WorldEvent).where(WorldEvent.digest == digest)
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
        row = WorldEvent(
            event_id=uuid7(),
            kind=kind,
            at=at,
            recorded_at=moment,
            entity_kind=entity_kind,
            entity_key=entity_key,
            payload=dict(payload),
            source=source,
            digest=digest,
        )
        session.add(row)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.WORLD_EVENT_RECORDED,
            actor=Actor.SYSTEM,
            subject=f"{entity_kind}:{entity_key}",
            payload={
                "kind": kind,
                "at": isoformat(at),
                "source": source,
                "digest": digest[:16],
            },
            at=moment,
        )
        return row, True

    @staticmethod
    def events_for(
        session: Session,
        *,
        entity_kind: str,
        entity_key: str,
        since: dt.datetime | None = None,
        kinds: tuple[str, ...] = (),
        limit: int = 50,
    ) -> list[WorldEvent]:
        """What happened to one entity, newest first."""
        query = sa.select(WorldEvent).where(
            WorldEvent.entity_kind == entity_kind, WorldEvent.entity_key == entity_key
        )
        if since is not None:
            query = query.where(WorldEvent.at >= since)
        if kinds:
            query = query.where(WorldEvent.kind.in_(kinds))
        return list(session.execute(query.order_by(WorldEvent.at.desc()).limit(limit)).scalars())

    @staticmethod
    def events_between(
        session: Session,
        *,
        since: dt.datetime,
        until: dt.datetime,
        kinds: tuple[str, ...] = (),
        limit: int = 500,
    ) -> list[WorldEvent]:
        query = sa.select(WorldEvent).where(WorldEvent.at >= since, WorldEvent.at < until)
        if kinds:
            query = query.where(WorldEvent.kind.in_(kinds))
        return list(session.execute(query.order_by(WorldEvent.at).limit(limit)).scalars())

    @staticmethod
    def co_occurrences(
        session: Session,
        *,
        first_kind: str,
        second_kind: str,
        within: dt.timedelta,
        since: dt.datetime | None = None,
        limit: int = 200,
    ) -> list[CoOccurrence]:
        """Pairs of events of two kinds on the same entity, the second inside
        ``within`` after the first. The primitive a scheme is built from.

        Deterministic and in software. What it returns is a list of
        conjunctions, not a discovery: a conjunction becomes a discovery only
        when an agent states a mechanism and the mechanism predicts something
        else that is then tested. See the brief, and ADR-0030.
        """
        query = sa.select(WorldEvent).where(WorldEvent.kind.in_((first_kind, second_kind)))
        if since is not None:
            query = query.where(WorldEvent.at >= since)
        rows = list(session.execute(query.order_by(WorldEvent.at)).scalars())
        by_entity: dict[tuple[str, str], list[WorldEvent]] = {}
        for row in rows:
            by_entity.setdefault((row.entity_kind, row.entity_key), []).append(row)
        out: list[CoOccurrence] = []
        for (ekind, ekey), events in by_entity.items():
            firsts = [e for e in events if e.kind == first_kind]
            seconds = [e for e in events if e.kind == second_kind]
            for first in firsts:
                for second in seconds:
                    if first.at <= second.at <= first.at + within:
                        out.append(CoOccurrence(ekind, ekey, first, second))
                        if len(out) >= limit:
                            return out
        return out

    # ---------------------------------------------------------------- relations

    def relate(
        self,
        session: Session,
        *,
        subject: tuple[str, str],
        kind: str,
        obj: tuple[str, str],
        source: str,
        at: dt.datetime | None = None,
    ) -> tuple[Relation, bool]:
        moment = at or self._clock.now()
        existing = session.execute(
            sa.select(Relation).where(
                Relation.subject_kind == subject[0],
                Relation.subject_key == subject[1],
                Relation.kind == kind,
                Relation.object_kind == obj[0],
                Relation.object_key == obj[1],
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
        row = Relation(
            relation_id=uuid7(),
            subject_kind=subject[0],
            subject_key=subject[1],
            kind=kind,
            object_kind=obj[0],
            object_key=obj[1],
            source=source,
            recorded_at=moment,
        )
        session.add(row)
        session.flush()
        return row, True

    @staticmethod
    def relations_of(session: Session, kind: str, key: str) -> list[Relation]:
        return list(
            session.execute(
                sa.select(Relation).where(
                    sa.or_(
                        sa.and_(Relation.subject_kind == kind, Relation.subject_key == key),
                        sa.and_(Relation.object_kind == kind, Relation.object_key == key),
                    )
                )
            ).scalars()
        )

    # ---------------------------------------------------------------- counts

    @staticmethod
    def counts(session: Session) -> dict[str, int]:
        return {
            "entities": int(
                session.execute(sa.select(sa.func.count()).select_from(Entity)).scalar_one()
            ),
            "events": int(
                session.execute(sa.select(sa.func.count()).select_from(WorldEvent)).scalar_one()
            ),
            "relations": int(
                session.execute(sa.select(sa.func.count()).select_from(Relation)).scalar_one()
            ),
        }
