"""Engine and session construction.

Two SQLite pragmas are set on every connection and both are load-bearing:

``foreign_keys=ON``
    SQLite does not enforce foreign keys unless asked, per connection. Several
    of the company's rules — an approval requires an assessment, an order
    requires an approval — are foreign keys. Without this pragma they are
    documentation.

``journal_mode=WAL``
    Readers do not block the writer. The station reads continuously while
    agents append, and the default rollback journal would have them contend.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from aurelis.core.config import Settings
from aurelis.platform.db.tables import Base
from aurelis.platform.db.triggers import install_invariants

__all__ = ["Database", "create_engine"]


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def create_engine(url: str, *, echo: bool = False) -> sa.Engine:
    """Build an engine with Aurelis's connection settings applied."""
    engine = sa.create_engine(url, echo=echo, future=True)
    if engine.dialect.name == "sqlite":
        sa.event.listen(engine, "connect", _configure_sqlite)
    return engine


class Database:
    """Owns the engine and hands out sessions."""

    __slots__ = ("_engine", "_sessionmaker", "settings")

    def __init__(self, settings: Settings, *, echo: bool = False) -> None:
        self.settings = settings
        url = settings.resolved_database_url
        if url.startswith("sqlite") and ":memory:" not in url:
            # Fail early and clearly rather than letting SQLite create a file
            # in a directory the operator did not intend.
            target = Path(url.split("///", 1)[1])
            target.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(url, echo=echo)
        self._sessionmaker = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)

    @property
    def engine(self) -> sa.Engine:
        return self._engine

    @property
    def dialect(self) -> str:
        return self._engine.dialect.name

    def create_all(self, *, install_triggers: bool = True) -> tuple[str, ...]:
        """Create the schema and install the invariant triggers.

        Returns the trigger names installed. Idempotent: safe to run against a
        live workspace.
        """
        # Importing the schema module registers every table. Without it,
        # `create_all` would build whatever happened to be imported first,
        # and the write-scope guards would try to protect tables that do not
        # exist.
        import aurelis.schema  # noqa: F401

        Base.metadata.create_all(self._engine)
        if not install_triggers:
            return ()
        with self._engine.begin() as connection:
            return install_invariants(connection)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A session with commit-or-rollback semantics.

        Aurelis writes a state change and the events describing it in the same
        transaction, so the two cannot disagree. That is the reason the queue
        lives in the database rather than in a broker.
        """
        session = self._sessionmaker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self._engine.dispose()
