"""The content-addressed artifact store.

Every number that reaches the company's record names the artifact it was read
out of, and every artifact is addressed by the SHA-256 of its own bytes. That
is the whole provenance mechanism: a citation cannot drift from what it cites,
because changing the content changes the address.

Files live at ``objects/<aa>/<bb>/<digest>`` — two levels of fan-out so a
directory listing stays usable at a few million artifacts, which is roughly
what a few years of experiments would produce.

Writes are atomic: content goes to a temporary file and is then renamed into
place. A crash can leave a stray temporary file, never a half-written artifact
that something else will happily hash and cite.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import canonical_bytes, sha256_of
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.platform.db.tables import Artifact
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["ArtifactStore", "StoredArtifact"]

_FANOUT = 2


@dataclass(frozen=True)
class StoredArtifact:
    """What a caller needs after storing: the address and whether it was new."""

    digest: str
    kind: str
    size_bytes: int
    already_present: bool

    @property
    def short(self) -> str:
        return self.digest[:12]


class ArtifactStore:
    """Immutable blob storage, addressed by content hash."""

    __slots__ = ("_clock", "_ledger", "root")

    def __init__(
        self, root: Path, ledger: Ledger | None = None, clock: Clock | None = None
    ) -> None:
        self.root = Path(root)
        self._ledger = ledger or Ledger(clock)
        self._clock = clock or SystemClock()

    # ---------------------------------------------------------------- paths

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
            raise ValueError(f"not a sha256 digest: {digest!r}")
        return self.root / digest[:_FANOUT] / digest[_FANOUT : _FANOUT * 2] / digest

    # --------------------------------------------------------------- writing

    def put(
        self,
        session: Session,
        content: bytes,
        *,
        kind: str,
        media_type: str = "application/octet-stream",
        produced_by: str | None = None,
        actor: Actor | str = Actor.SYSTEM,
    ) -> StoredArtifact:
        """Store ``content`` and return its address.

        Storing content that is already present is a no-op that returns the
        same digest. Identical content really is the same artifact — that is
        what content-addressing means — and it is also free experiment
        deduplication: a re-run that produces byte-identical output costs one
        hash and no storage.
        """
        digest = sha256_of(content)
        existing = session.get(Artifact, digest)
        if existing is not None:
            if existing.size_bytes != len(content):
                # Would mean a SHA-256 collision or a corrupted row. Either way
                # the store's core promise is void and it must not be papered over.
                raise IntegrityViolation(
                    f"artifact {digest[:12]} exists with size {existing.size_bytes} "
                    f"but new content is {len(content)} bytes"
                )
            self._ensure_file(digest, content)
            return StoredArtifact(digest, existing.kind, existing.size_bytes, True)

        self._ensure_file(digest, content)
        session.add(
            Artifact(
                digest=digest,
                kind=kind,
                media_type=media_type,
                size_bytes=len(content),
                produced_by=produced_by,
                created_at=self._clock.now(),
            )
        )
        self._ledger.append(
            session,
            kind=EventKind.ARTIFACT_STORED,
            actor=actor,
            subject=digest[:12],
            payload={
                "digest": digest,
                "kind": kind,
                "media_type": media_type,
                "size_bytes": len(content),
                "produced_by": produced_by,
            },
        )
        return StoredArtifact(digest, kind, len(content), False)

    def put_json(
        self,
        session: Session,
        payload: object,
        *,
        kind: str,
        produced_by: str | None = None,
        actor: Actor | str = Actor.SYSTEM,
    ) -> StoredArtifact:
        """Store a structure through the canonical encoder.

        Canonical rather than ``json.dumps`` so that the same logical result
        always lands on the same digest, whatever order a dict was built in.
        """
        return self.put(
            session,
            canonical_bytes(payload),
            kind=kind,
            media_type="application/json",
            produced_by=produced_by,
            actor=actor,
        )

    def _ensure_file(self, digest: str, content: bytes) -> None:
        target = self.path_for(digest)
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    # --------------------------------------------------------------- reading

    def get(self, digest: str) -> bytes:
        """Read an artifact back, re-verifying its hash.

        Re-hashing on every read is cheap next to the cost of citing a
        corrupted artifact as evidence.
        """
        path = self.path_for(digest)
        if not path.exists():
            raise FileNotFoundError(f"artifact {digest[:12]} is recorded but its file is missing")
        content = path.read_bytes()
        actual = sha256_of(content)
        if actual != digest:
            raise IntegrityViolation(
                f"artifact {digest[:12]} does not hash to its address "
                f"(file hashes to {actual[:12]}) — the store is corrupted"
            )
        return content

    def exists(self, digest: str) -> bool:
        return self.path_for(digest).exists()

    # ------------------------------------------------------------- integrity

    def verify(self, session: Session) -> tuple[list[str], list[str]]:
        """Check every recorded artifact against its file.

        Returns ``(missing, corrupted)`` digests. Reported by ``aurelis
        doctor``.
        """
        missing: list[str] = []
        corrupted: list[str] = []
        digests = session.execute(sa.select(Artifact.digest)).scalars().all()
        for digest in digests:
            path = self.path_for(digest)
            if not path.exists():
                missing.append(digest)
            elif sha256_of(path.read_bytes()) != digest:
                corrupted.append(digest)
        return missing, corrupted
