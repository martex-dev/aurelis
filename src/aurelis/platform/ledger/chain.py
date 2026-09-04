"""The event hash chain.

Each event carries a hash of its own payload and a ``chain_hash`` binding it to
its predecessor. Editing any historical event — its payload, its actor, its
timestamp, its subject — changes that event's chain hash, which no longer
matches the ``prev_hash`` recorded by the next one, and verification fails at
a named sequence number.

This makes the ledger **tamper-evident**, which is a weaker and more honest
property than tamper-proof. Someone with write access to the database can still
alter it; they cannot do so without ``aurelis ledger verify`` noticing.
Combined with the append-only triggers, that is a reasonable standard for a
single-tenant research instrument, and overstating it would be exactly the kind
of unearned claim this project exists to avoid.

Deleting a trailing run of events is the one edit a pure chain cannot detect,
because the remaining prefix still links perfectly. Verification therefore also
checks that sequence numbers are dense from 1.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from aurelis.core.canonical import sha256_of
from aurelis.core.clock import isoformat

__all__ = [
    "ChainVerification",
    "EventRow",
    "GENESIS",
    "chain_hash",
    "payload_hash",
    "verify_chain",
]

GENESIS: str | None = None
"""``prev_hash`` of the first event: a chain with no predecessor."""

_FIELD_SEPARATOR = "\x1f"
"""ASCII unit separator. A character that cannot occur in any hashed field, so
concatenation is unambiguous — otherwise an actor ending in a delimiter could
be made to look like a different actor plus a different kind."""


class EventRow(Protocol):
    """The subset of :class:`~aurelis.platform.db.tables.Event` verification reads."""

    seq: int
    event_id: uuid.UUID
    actor: str
    kind: str
    subject: str | None
    payload: dict[str, Any]
    payload_hash: str
    prev_hash: str | None
    chain_hash: str
    created_at: dt.datetime


def payload_hash(payload: dict[str, Any]) -> str:
    """Hash of the event's own content, independent of its position."""
    return sha256_of(payload)


def chain_hash(
    *,
    seq: int,
    event_id: uuid.UUID,
    actor: str,
    kind: str,
    subject: str | None,
    payload_digest: str,
    prev_hash: str | None,
    created_at: dt.datetime,
) -> str:
    """Bind this event to its predecessor.

    Every field that an auditor would care about is in the preimage. Leaving
    one out — the actor, say — would let it be rewritten without detection,
    which would make "who did this?" unanswerable while the chain still
    verified.
    """
    preimage = _FIELD_SEPARATOR.join(
        (
            str(seq),
            str(event_id),
            actor,
            kind,
            subject or "",
            payload_digest,
            prev_hash or "",
            isoformat(created_at),
        )
    )
    return sha256_of(preimage.encode("utf-8"))


@dataclass(frozen=True)
class ChainVerification:
    """Outcome of a verification pass."""

    checked: int
    ok: bool
    broken_at: int | None = None
    reason: str | None = None
    first_seq: int | None = None
    last_seq: int | None = None

    def describe(self) -> str:
        if self.ok:
            return f"chain verified: {self.checked} events, seq {self.first_seq}..{self.last_seq}"
        return f"chain BROKEN at seq {self.broken_at}: {self.reason}"


def verify_chain(events: list[EventRow]) -> ChainVerification:
    """Walk the chain in sequence order and check every link.

    ``events`` must be ordered by ``seq``. Four things are checked, and the
    third and fourth are the ones people forget: that the payload still hashes
    to its recorded digest (content was not edited under a stale hash), and
    that no sequence numbers are missing (nothing was excised wholesale).
    """
    if not events:
        return ChainVerification(checked=0, ok=True, first_seq=None, last_seq=None)

    expected_prev: str | None = GENESIS
    previous_seq: int | None = None

    for event in events:
        if previous_seq is None:
            if event.seq != 1:
                return ChainVerification(
                    checked=0,
                    ok=False,
                    broken_at=event.seq,
                    reason=(
                        f"chain starts at seq {event.seq}, not 1 — "
                        f"{event.seq - 1} leading events are missing"
                    ),
                )
        elif event.seq != previous_seq + 1:
            return ChainVerification(
                checked=event.seq - 1,
                ok=False,
                broken_at=event.seq,
                reason=(
                    f"sequence gap: {event.seq - previous_seq - 1} event(s) missing "
                    f"between seq {previous_seq} and {event.seq}"
                ),
            )

        recomputed_payload = payload_hash(event.payload)
        if recomputed_payload != event.payload_hash:
            return ChainVerification(
                checked=event.seq - 1,
                ok=False,
                broken_at=event.seq,
                reason="payload does not match its recorded hash — content was edited",
            )

        if event.prev_hash != expected_prev:
            return ChainVerification(
                checked=event.seq - 1,
                ok=False,
                broken_at=event.seq,
                reason=(
                    f"prev_hash {event.prev_hash!r} does not match the previous "
                    f"event's chain_hash {expected_prev!r}"
                ),
            )

        recomputed_chain = chain_hash(
            seq=event.seq,
            event_id=event.event_id,
            actor=event.actor,
            kind=event.kind,
            subject=event.subject,
            payload_digest=recomputed_payload,
            prev_hash=event.prev_hash,
            created_at=event.created_at,
        )
        if recomputed_chain != event.chain_hash:
            return ChainVerification(
                checked=event.seq - 1,
                ok=False,
                broken_at=event.seq,
                reason="chain_hash does not match its own fields — the event was altered",
            )

        expected_prev = event.chain_hash
        previous_seq = event.seq

    return ChainVerification(
        checked=len(events),
        ok=True,
        first_seq=events[0].seq,
        last_seq=events[-1].seq,
    )
