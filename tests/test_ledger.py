"""The event ledger: chaining, verification, and tamper detection.

The tamper tests write through raw SQL after disabling the triggers, which is
exactly the threat model: someone with database access editing history. The
claim is that verification *notices*, not that the edit is impossible.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import uuid7
from aurelis.platform.db.tables import Event
from aurelis.platform.ledger.chain import GENESIS, chain_hash, payload_hash, verify_chain
from aurelis.platform.ledger.ledger import Ledger
from aurelis.runtime import Runtime


def _append(runtime: Runtime, n: int) -> None:
    with runtime.database.session() as session:
        for i in range(n):
            runtime.ledger.append(
                session,
                kind=EventKind.DEMO_EXCHANGE,
                actor=Actor.SYSTEM,
                subject=f"SUB-{i}",
                payload={"index": i},
            )


def _drop_triggers(runtime: Runtime) -> None:
    """Remove the append-only triggers so a test can play the attacker."""
    with runtime.database.engine.begin() as connection:
        for name in connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='trigger'")
        ).scalars():
            connection.execute(sa.text(f"DROP TRIGGER {name}"))


# ------------------------------------------------------------------ chaining


def test_first_event_starts_at_seq_one_with_no_predecessor(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        first = session.execute(sa.select(Event).order_by(Event.seq)).scalars().first()
    assert first is not None
    assert first.seq == 1
    assert first.prev_hash is GENESIS


def test_each_event_links_to_its_predecessor(runtime: Runtime) -> None:
    _append(runtime, 5)
    with runtime.database.session() as session:
        events = session.execute(sa.select(Event).order_by(Event.seq)).scalars().all()
    for earlier, later in zip(events, events[1:], strict=False):
        assert later.prev_hash == earlier.chain_hash


def test_sequence_numbers_are_dense(runtime: Runtime) -> None:
    _append(runtime, 10)
    with runtime.database.session() as session:
        seqs = session.execute(sa.select(Event.seq).order_by(Event.seq)).scalars().all()
    assert seqs == list(range(1, len(seqs) + 1))


def test_verification_passes_on_an_honest_chain(runtime: Runtime) -> None:
    _append(runtime, 8)
    with runtime.database.session() as session:
        result = runtime.ledger.verify(session)
    assert result.ok
    assert result.checked == result.last_seq


def test_empty_chain_verifies(runtime: Runtime) -> None:
    assert verify_chain([]).ok


# ---------------------------------------------------------- tamper detection


def test_edited_payload_is_detected(runtime: Runtime) -> None:
    """Content edited under a stale hash: the payload no longer matches."""
    _append(runtime, 5)
    _drop_triggers(runtime)
    with runtime.database.engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE events SET payload = :p WHERE seq = 3"),
            {"p": '{"index": 999}'},
        )

    with runtime.database.session() as session:
        result = runtime.ledger.verify(session)
    assert not result.ok
    assert result.broken_at == 3
    assert "payload does not match" in (result.reason or "")


def test_edited_actor_is_detected(runtime: Runtime) -> None:
    """Rewriting who did something must not survive verification."""
    _append(runtime, 5)
    _drop_triggers(runtime)
    with runtime.database.engine.begin() as connection:
        connection.execute(sa.text("UPDATE events SET actor = 'someone-else' WHERE seq = 4"))

    with runtime.database.session() as session:
        result = runtime.ledger.verify(session)
    assert not result.ok
    assert result.broken_at == 4


def test_deleted_middle_event_is_detected_as_a_gap(runtime: Runtime) -> None:
    _append(runtime, 6)
    _drop_triggers(runtime)
    with runtime.database.engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM events WHERE seq = 4"))

    with runtime.database.session() as session:
        result = runtime.ledger.verify(session)
    assert not result.ok
    assert "sequence gap" in (result.reason or "")


def test_deleted_leading_events_are_detected(runtime: Runtime) -> None:
    """A truncated prefix still links perfectly; only density catches it."""
    _append(runtime, 6)
    _drop_triggers(runtime)
    with runtime.database.engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM events WHERE seq <= 2"))

    with runtime.database.session() as session:
        result = runtime.ledger.verify(session)
    assert not result.ok
    assert "not 1" in (result.reason or "")


def test_reinserted_event_with_recomputed_hash_still_breaks_the_next_link(
    runtime: Runtime,
) -> None:
    """A sophisticated forgery: fix the event's own hash but not its successor's.

    This is the case the chain exists for. Recomputing one event's chain_hash
    makes that event internally consistent, and the very next event's
    ``prev_hash`` no longer matches.
    """
    _append(runtime, 5)
    _drop_triggers(runtime)

    clock = FrozenClock(dt.datetime(2026, 9, 4, tzinfo=dt.UTC))
    with runtime.database.session() as session:
        target = session.execute(sa.select(Event).where(Event.seq == 3)).scalar_one()
        forged_payload = {"index": 999}
        digest = payload_hash(forged_payload)
        forged_chain = chain_hash(
            seq=target.seq,
            event_id=target.event_id,
            actor=target.actor,
            kind=target.kind,
            subject=target.subject,
            payload_digest=digest,
            prev_hash=target.prev_hash,
            created_at=clock.now(),
        )

    with runtime.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE events SET payload=:p, payload_hash=:d, chain_hash=:c, "
                "created_at=:t WHERE seq=3"
            ),
            {
                "p": '{"index": 999}',
                "d": digest,
                "c": forged_chain,
                # Bound as text: the sqlite3 datetime adapter is deprecated,
                # and this is the storage form UtcDateTime writes anyway.
                "t": clock.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            },
        )

    with runtime.database.session() as session:
        result = runtime.ledger.verify(session)
    assert not result.ok
    assert result.broken_at == 4, "the forgery should surface at the next event's prev_hash"


# ------------------------------------------------------------------- reading


def test_for_subject_returns_one_entity_history(runtime: Runtime) -> None:
    _append(runtime, 6)
    with runtime.database.session() as session:
        history = runtime.ledger.for_subject(session, "SUB-2")
    assert len(history) == 1
    assert history[0].payload["index"] == 2


def test_since_feeds_the_live_view(runtime: Runtime) -> None:
    _append(runtime, 4)
    with runtime.database.session() as session:
        head = runtime.ledger.count(session)
        runtime.ledger.append(session, kind=EventKind.DEMO_EXCHANGE, payload={"index": 99})
    with runtime.database.session() as session:
        fresh = runtime.ledger.since(session, head)
    assert [e.payload["index"] for e in fresh] == [99]


def test_tail_is_oldest_first_within_the_window(runtime: Runtime) -> None:
    _append(runtime, 10)
    with runtime.database.session() as session:
        tail = runtime.ledger.tail(session, limit=3)
    assert [e.seq for e in tail] == sorted(e.seq for e in tail)


def test_hash_covers_every_audited_field() -> None:
    """Changing any hashed field must change the chain hash.

    If a field were left out of the preimage it could be rewritten without
    detection while the chain still verified — which would make "who did
    this?" unanswerable.
    """
    moment = dt.datetime(2026, 9, 4, tzinfo=dt.UTC)
    base = {
        "seq": 7,
        "event_id": uuid7(now_ms=1_700_000_000_000),
        "actor": "AG-0001",
        "kind": "demo.exchange",
        "subject": "MSN-0001",
        "payload_digest": payload_hash({"a": 1}),
        "prev_hash": "0" * 64,
        "created_at": moment,
    }
    reference = chain_hash(**base)  # type: ignore[arg-type]

    variants = {
        "seq": {**base, "seq": 8},
        "actor": {**base, "actor": "AG-0002"},
        "kind": {**base, "kind": "demo.other"},
        "subject": {**base, "subject": "MSN-0002"},
        "payload": {**base, "payload_digest": payload_hash({"a": 2})},
        "prev_hash": {**base, "prev_hash": "1" * 64},
        "created_at": {**base, "created_at": moment + dt.timedelta(seconds=1)},
    }
    for field, variant in variants.items():
        assert chain_hash(**variant) != reference, f"{field} is not covered by the chain hash"


def test_separator_prevents_field_boundary_ambiguity() -> None:
    """Concatenation must not let one field masquerade as two."""
    moment = dt.datetime(2026, 9, 4, tzinfo=dt.UTC)
    common = {
        "seq": 1,
        "event_id": uuid7(now_ms=1_700_000_000_000),
        "payload_digest": "0" * 64,
        "prev_hash": None,
        "created_at": moment,
    }
    a = chain_hash(actor="abc", kind="def", subject=None, **common)  # type: ignore[arg-type]
    b = chain_hash(actor="ab", kind="cdef", subject=None, **common)  # type: ignore[arg-type]
    assert a != b


def test_append_is_rejected_by_the_trigger_on_update(runtime: Runtime) -> None:
    """The append-only rule applies to Aurelis's own code too."""
    _append(runtime, 2)
    with pytest.raises(Exception, match="append-only"), runtime.database.engine.begin() as conn:
        conn.execute(sa.text("UPDATE events SET actor='x' WHERE seq=1"))


def test_ledger_instances_share_the_chain(runtime: Runtime) -> None:
    """A second Ledger object must continue the chain, not start a new one."""
    _append(runtime, 3)
    other = Ledger(runtime.clock)
    with runtime.database.session() as session:
        before = runtime.ledger.count(session)
        event = other.append(session, kind=EventKind.DEMO_EXCHANGE, payload={"from": "other"})
        assert event.seq == before + 1
        assert runtime.ledger.verify(session).ok
