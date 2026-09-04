"""Appending to, and reading from, the company's record.

Every append happens inside the caller's session, never in one of its own.
That is the point of putting the ledger in the same database as everything
else: a task moving to ``succeeded`` and the event describing what it produced
must commit together or not at all, and a ledger with its own transaction
could not promise that.

Sequence allocation is left to the database's autoincrement, and the chain is
computed after the insert flushes, because the sequence number is part of the
hash preimage. Under concurrent writers this needs the insert and the hash
update to be serialised; SQLite gives that for free with a single writer, and
:meth:`Ledger.append` takes a lock on Postgres.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import uuid7
from aurelis.platform.db.tables import Event
from aurelis.platform.ledger.chain import ChainVerification, chain_hash, payload_hash, verify_chain

__all__ = ["Ledger"]


class Ledger:
    """Append-only, hash-chained record of everything that happened."""

    __slots__ = ("_clock",)

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()

    # ------------------------------------------------------------- writing

    def append(
        self,
        session: Session,
        *,
        kind: EventKind | str,
        actor: Actor | str = Actor.SYSTEM,
        subject: str | None = None,
        payload: dict[str, Any] | None = None,
        at: dt.datetime | None = None,
    ) -> Event:
        """Append one event inside the caller's transaction."""
        body = dict(payload or {})
        digest = payload_hash(body)
        created_at = at or self._clock.now()

        if session.bind is not None and session.bind.dialect.name == "postgresql":
            # Serialise chain construction: two concurrent appends must not
            # both read the same predecessor and claim the same sequence
            # number. SQLite's single-writer model gives this for free.
            session.execute(sa.text("LOCK TABLE events IN EXCLUSIVE MODE"))

        head = session.execute(
            sa.select(Event.seq, Event.chain_hash).order_by(Event.seq.desc()).limit(1)
        ).one_or_none()
        seq = 1 if head is None else int(head[0]) + 1
        previous_hash: str | None = None if head is None else str(head[1])

        event_id = uuid7()
        event = Event(
            seq=seq,
            event_id=event_id,
            actor=str(actor),
            kind=str(kind),
            subject=subject,
            payload=body,
            payload_hash=digest,
            prev_hash=previous_hash,
            chain_hash=chain_hash(
                seq=seq,
                event_id=event_id,
                actor=str(actor),
                kind=str(kind),
                subject=subject,
                payload_digest=digest,
                prev_hash=previous_hash,
                created_at=created_at,
            ),
            created_at=created_at,
        )
        session.add(event)
        session.flush()
        return event

    # ------------------------------------------------------------- reading

    def tail(self, session: Session, limit: int = 20) -> list[Event]:
        """The most recent events, oldest first within the window."""
        rows = session.execute(
            sa.select(Event).order_by(Event.seq.desc()).limit(limit)
        ).scalars().all()
        return list(reversed(rows))

    def since(self, session: Session, seq: int) -> list[Event]:
        """Everything after ``seq``, in order. The station's live feed."""
        return list(
            session.execute(sa.select(Event).where(Event.seq > seq).order_by(Event.seq))
            .scalars()
            .all()
        )

    def for_subject(self, session: Session, subject: str) -> list[Event]:
        """One entity's whole history — the basis of every drill-down view."""
        return list(
            session.execute(
                sa.select(Event).where(Event.subject == subject).order_by(Event.seq)
            )
            .scalars()
            .all()
        )

    def count(self, session: Session) -> int:
        total = session.execute(sa.select(sa.func.count()).select_from(Event)).scalar_one()
        return int(total)

    # -------------------------------------------------------- verification

    def verify(self, session: Session) -> ChainVerification:
        """Verify the whole chain.

        Reads every event. That is acceptable — verification is an audit
        operation run on demand and in CI, not on the request path — and doing
        it incrementally would mean trusting a checkpoint written by the same
        code the audit is checking.
        """
        events: Sequence[Event] = (
            session.execute(sa.select(Event).order_by(Event.seq)).scalars().all()
        )
        return verify_chain(list(events))
