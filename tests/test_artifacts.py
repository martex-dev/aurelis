"""The content-addressed artifact store."""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.core.canonical import sha256_of
from aurelis.core.errors import IntegrityViolation
from aurelis.platform.db.tables import Artifact
from aurelis.runtime import Runtime


def test_digest_is_the_hash_of_the_content(runtime: Runtime) -> None:
    payload = b"walk-forward result"
    with runtime.database.session() as session:
        stored = runtime.artifacts.put(session, payload, kind="result")
    assert stored.digest == sha256_of(payload)


def test_content_round_trips(runtime: Runtime) -> None:
    payload = b"equity curve bytes"
    with runtime.database.session() as session:
        stored = runtime.artifacts.put(session, payload, kind="result")
    assert runtime.artifacts.get(stored.digest) == payload


def test_identical_content_is_the_same_artifact(runtime: Runtime) -> None:
    """Free deduplication: a re-run producing identical bytes costs one hash."""
    with runtime.database.session() as session:
        first = runtime.artifacts.put(session, b"same", kind="result")
        second = runtime.artifacts.put(session, b"same", kind="result")
    assert first.digest == second.digest
    assert not first.already_present
    assert second.already_present


def test_duplicate_store_appends_only_one_event(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        before = runtime.ledger.count(session)
        runtime.artifacts.put(session, b"twice", kind="result")
        runtime.artifacts.put(session, b"twice", kind="result")
        after = runtime.ledger.count(session)
    assert after - before == 1


def test_canonical_json_makes_dict_order_irrelevant(runtime: Runtime) -> None:
    """The same logical result must always land on the same address."""
    with runtime.database.session() as session:
        a = runtime.artifacts.put_json(session, {"sharpe": Decimal("1.47"), "n": 2}, kind="m")
        b = runtime.artifacts.put_json(session, {"n": 2, "sharpe": Decimal("1.47")}, kind="m")
    assert a.digest == b.digest


def test_fanout_keeps_directories_small(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        stored = runtime.artifacts.put(session, b"fanned", kind="result")
    path = runtime.artifacts.path_for(stored.digest)
    assert path.parent.name == stored.digest[2:4]
    assert path.parent.parent.name == stored.digest[:2]
    assert path.exists()


def test_malformed_digest_is_refused(runtime: Runtime) -> None:
    with pytest.raises(ValueError, match="not a sha256 digest"):
        runtime.artifacts.path_for("not-a-hash")


def test_missing_file_is_reported_clearly(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        stored = runtime.artifacts.put(session, b"soon gone", kind="result")
    runtime.artifacts.path_for(stored.digest).unlink()
    with pytest.raises(FileNotFoundError, match="file is missing"):
        runtime.artifacts.get(stored.digest)


def test_corrupted_file_is_caught_on_read(runtime: Runtime) -> None:
    """Re-hashing on read is cheap next to citing a corrupted artifact."""
    with runtime.database.session() as session:
        stored = runtime.artifacts.put(session, b"original", kind="result")
    runtime.artifacts.path_for(stored.digest).write_bytes(b"tampered")
    with pytest.raises(IntegrityViolation, match="does not hash to its address"):
        runtime.artifacts.get(stored.digest)


def test_verify_reports_missing_and_corrupted(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        gone = runtime.artifacts.put(session, b"will vanish", kind="result")
        bad = runtime.artifacts.put(session, b"will rot", kind="result")
        runtime.artifacts.put(session, b"stays fine", kind="result")

    runtime.artifacts.path_for(gone.digest).unlink()
    runtime.artifacts.path_for(bad.digest).write_bytes(b"rotted")

    with runtime.database.session() as session:
        missing, corrupted = runtime.artifacts.verify(session)
    assert missing == [gone.digest]
    assert corrupted == [bad.digest]


def test_artifact_rows_are_append_only(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.artifacts.put(session, b"immutable", kind="result")
    with pytest.raises(Exception, match="append-only"), runtime.database.engine.begin() as conn:
        conn.execute(sa.text("UPDATE artifacts SET kind = 'edited'"))


def test_size_is_recorded(runtime: Runtime) -> None:
    payload = b"x" * 321
    with runtime.database.session() as session:
        stored = runtime.artifacts.put(session, payload, kind="result")
        row = session.execute(
            sa.select(Artifact).where(Artifact.digest == stored.digest)
        ).scalar_one()
    assert row.size_bytes == 321
    assert stored.size_bytes == 321
