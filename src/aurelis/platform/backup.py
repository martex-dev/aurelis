"""Backup and restore, verified rather than assumed.

A company whose entire record is one SQLite file and one directory of
content-addressed blobs is easy to back up and easy to back up *wrongly*. The
two failure modes that matter are both silent:

**A torn database.** Copying `aurelis.db` while a transaction is in flight
produces a file that opens without complaint and is missing the last write.
SQLite's own backup API takes a consistent snapshot under a read lock, so that
is what this uses — never a file copy.

**A backup nobody checked.** A restore that produces a database which opens is
not a restore. So :func:`restore` re-verifies the hash chain on the restored
copy and re-checks every artifact digest against its bytes, and it **refuses**
to report success if either fails. The chain is the whole point of the record;
a backup that silently dropped an event would be worse than no backup, because
the company would trust it.

The artifact store is content-addressed, which makes its integrity check exact
rather than approximate: every file's name is the hash of its contents, so a
corrupted blob is detected by rehashing it, and a missing one is detected by
the row that cites it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from aurelis import __version__
from aurelis.core.config import Settings

__all__ = ["BackupReport", "RestoreReport", "back_up", "restore", "verify_workspace"]

MANIFEST = "aurelis-backup.json"


@dataclass(frozen=True, slots=True)
class BackupReport:
    """What was written, and what it should contain when restored."""

    path: Path
    events: int
    head: str
    artifacts: int
    artifact_bytes: int
    database_bytes: int
    taken_at: dt.datetime
    version: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "events": self.events,
            "head": self.head,
            "artifacts": self.artifacts,
            "artifact_bytes": self.artifact_bytes,
            "database_bytes": self.database_bytes,
            "taken_at": self.taken_at.isoformat(),
            "aurelis_version": self.version,
        }

    def describe(self) -> str:
        return (
            f"{self.events} events (head {self.head[:12]}), "
            f"{self.artifacts} artifacts, "
            f"{self.database_bytes + self.artifact_bytes} bytes"
        )


@dataclass(frozen=True, slots=True)
class RestoreReport:
    """What came back, and whether it survived the trip."""

    path: Path
    events: int
    head: str
    artifacts: int
    chain_ok: bool
    artifacts_ok: bool
    expected: dict[str, Any] = field(default_factory=dict)
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """A restore that opens is not a restore. This is the real question."""
        return self.chain_ok and self.artifacts_ok and not self.problems

    def as_payload(self) -> dict[str, Any]:
        return {
            "events": self.events,
            "head": self.head,
            "artifacts": self.artifacts,
            "chain_ok": self.chain_ok,
            "artifacts_ok": self.artifacts_ok,
            "problems": list(self.problems),
            "ok": self.ok,
        }

    def describe(self) -> str:
        if self.ok:
            return (
                f"restored {self.events} events (head {self.head[:12]}) and "
                f"{self.artifacts} artifacts; chain verifies, every digest matches"
            )
        return "RESTORE FAILED: " + "; ".join(self.problems)


def back_up(settings: Settings, destination: Path) -> BackupReport:
    """Take a consistent snapshot of a workspace.

    The database goes through SQLite's backup API rather than a file copy: a
    copy taken mid-transaction opens without complaint and is missing the last
    write, which is the kind of corruption that is only discovered when it is
    needed.
    """
    from aurelis.platform.db.session import Database
    from aurelis.platform.ledger.ledger import Ledger

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    database = Database(settings)
    try:
        with database.session() as session:
            ledger = Ledger()
            events = ledger.count(session)
            head = _head(session)
        source_path = _sqlite_path(settings)
        target = destination / "aurelis.db"
        _snapshot(source_path, target)
    finally:
        database.dispose()

    objects = destination / "objects"
    if objects.exists():
        shutil.rmtree(objects)
    artifact_count = 0
    artifact_bytes = 0
    if settings.object_store.exists():
        shutil.copytree(settings.object_store, objects)
        for path in objects.rglob("*"):
            if path.is_file():
                artifact_count += 1
                artifact_bytes += path.stat().st_size

    report = BackupReport(
        path=destination,
        events=events,
        head=head,
        artifacts=artifact_count,
        artifact_bytes=artifact_bytes,
        database_bytes=target.stat().st_size,
        taken_at=dt.datetime.now(dt.UTC),
        version=__version__,
    )
    # The manifest is what makes a restore checkable. Without the expected
    # event count and head, a restore can only report that a file opened.
    (destination / MANIFEST).write_text(
        json.dumps(report.as_payload(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def restore(source: Path, settings: Settings) -> RestoreReport:
    """Restore a workspace, then check that it is really the same one.

    Refuses to report success on a chain that does not verify or an artifact
    whose bytes no longer hash to its name.
    """
    source = Path(source)
    manifest_path = source / MANIFEST
    if not manifest_path.exists():
        return RestoreReport(
            path=source,
            events=0,
            head="",
            artifacts=0,
            chain_ok=False,
            artifacts_ok=False,
            problems=(
                f"no {MANIFEST} in {source}; without it a restore can only "
                "report that a file opened, not that it is the right file",
            ),
        )
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))

    settings.ensure_workspace()
    shutil.copy2(source / "aurelis.db", _sqlite_path(settings))
    if (source / "objects").exists():
        if settings.object_store.exists():
            shutil.rmtree(settings.object_store)
        shutil.copytree(source / "objects", settings.object_store)

    checked = verify_workspace(settings)
    problems = list(checked.problems)
    if checked.events != expected.get("events"):
        problems.append(
            f"expected {expected.get('events')} events, restored {checked.events}"
        )
    if checked.head != expected.get("head"):
        problems.append("the chain head does not match the manifest")
    if checked.artifacts != expected.get("artifacts"):
        problems.append(
            f"expected {expected.get('artifacts')} artifacts, restored "
            f"{checked.artifacts}"
        )
    return RestoreReport(
        path=source,
        events=checked.events,
        head=checked.head,
        artifacts=checked.artifacts,
        chain_ok=checked.chain_ok,
        artifacts_ok=checked.artifacts_ok,
        expected=expected,
        problems=tuple(problems),
    )


def verify_workspace(settings: Settings) -> RestoreReport:
    """Check a live workspace: the chain, and every artifact's digest.

    Used by ``restore`` and by ``aurelis doctor``. The artifact check is exact
    rather than approximate because the store is content-addressed -- a file's
    name *is* the hash of its contents, so corruption is caught by rehashing.
    """
    from aurelis.platform.db.session import Database
    from aurelis.platform.ledger.ledger import Ledger

    problems: list[str] = []
    database = Database(settings)
    try:
        with database.session() as session:
            ledger = Ledger()
            events = ledger.count(session)
            verification = ledger.verify(session)
            head = _head(session)
            digests = _artifact_digests(session)
    finally:
        database.dispose()

    if not verification.ok:
        problems.append(f"chain broken: {verification.describe()}")

    missing: list[str] = []
    corrupt: list[str] = []
    for digest in digests:
        path = _blob_path(settings.object_store, digest)
        if path is None:
            missing.append(digest[:12])
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            corrupt.append(digest[:12])
    if missing:
        problems.append(f"{len(missing)} artifact(s) cited but absent: {missing[:5]}")
    if corrupt:
        problems.append(
            f"{len(corrupt)} artifact(s) whose bytes no longer hash to their "
            f"name: {corrupt[:5]}"
        )

    stored = (
        sum(1 for p in settings.object_store.rglob("*") if p.is_file())
        if settings.object_store.exists()
        else 0
    )
    return RestoreReport(
        path=settings.workspace,
        events=events,
        head=head,
        artifacts=stored,
        chain_ok=verification.ok,
        artifacts_ok=not missing and not corrupt,
        problems=tuple(problems),
    )


# ------------------------------------------------------------------ helpers


def _sqlite_path(settings: Settings) -> Path:
    url = settings.resolved_database_url
    if not url.startswith("sqlite"):
        raise NotImplementedError(
            "backup is written for SQLite workspaces. A Postgres deployment "
            "backs up through its own tooling, and pretending otherwise would "
            "hand an operator a file that is not a backup."
        )
    return Path(url.split("///", 1)[1])


def _snapshot(source: Path, target: Path) -> None:
    """SQLite's own backup API. Consistent under concurrent writes."""
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _head(session: Any) -> str:
    from aurelis.platform.db.tables import Event

    value = session.execute(
        sa.select(Event.chain_hash).order_by(Event.seq.desc()).limit(1)
    ).scalar_one_or_none()
    return str(value or "")


def _artifact_digests(session: Any) -> tuple[str, ...]:
    from aurelis.platform.db.tables import Artifact

    return tuple(
        str(d) for d in session.execute(sa.select(Artifact.digest)).scalars()
    )


def _blob_path(store: Path, digest: str) -> Path | None:
    """Where the store put this blob.

    The layout is the store's, read from it rather than reimplemented here: a
    second copy of the sharding rule would drift, and the failure would be a
    backup that reported every artifact missing.
    """
    from aurelis.platform.artifacts.store import blob_path

    path = blob_path(store, digest)
    return path if path.exists() else None
