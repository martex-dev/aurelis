"""Invariants expressed as database triggers.

A rule enforced only by the application is a convention: it holds until
someone opens a SQL console, writes a migration, or adds a code path that
forgets. These triggers hold against raw SQL, which is the standard the
company's record has to meet — the whole value of an auditable ledger is that
it is auditable by someone who does not trust the code that wrote it.

The rules at M0:

``append_only``
    ``UPDATE`` and ``DELETE`` are refused on the ledger tables. History is not
    editable, so an event cannot be quietly revised and a cost cannot be
    quietly forgiven.

``artifact_content_immutable``
    Redundant with append-only, and installed anyway: an artifact's digest is
    the hash of its content, so a row whose digest no longer matches its bytes
    would break every provenance claim that cites it.

Both are installed on SQLite and Postgres in each dialect's own syntax.
:func:`verify_invariants` re-derives what should be present, so ``aurelis
doctor`` can report a database whose protection was dropped.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

from aurelis.platform.db.tables import APPEND_ONLY_TABLES

__all__ = [
    "expected_trigger_names",
    "install_invariants",
    "verify_invariants",
]

_REFUSAL = "Aurelis: {table} is append-only; history is not editable"


def expected_trigger_names() -> tuple[str, ...]:
    names: list[str] = []
    for table in APPEND_ONLY_TABLES:
        names.append(f"aurelis_{table}_no_update")
        names.append(f"aurelis_{table}_no_delete")
    return tuple(sorted(names))


def _sqlite_statements() -> Iterator[str]:
    for table in APPEND_ONLY_TABLES:
        message = _REFUSAL.format(table=table)
        for verb in ("update", "delete"):
            yield (
                f"CREATE TRIGGER IF NOT EXISTS aurelis_{table}_no_{verb} "
                f"BEFORE {verb.upper()} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
            )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_refuse_write() RETURNS trigger AS $$ "
        "BEGIN RAISE EXCEPTION 'Aurelis: %% is append-only; history is not editable', "
        "TG_TABLE_NAME; END; $$ LANGUAGE plpgsql"
    )
    for table in APPEND_ONLY_TABLES:
        for verb in ("update", "delete"):
            name = f"aurelis_{table}_no_{verb}"
            yield f"DROP TRIGGER IF EXISTS {name} ON {table}"
            yield (
                f"CREATE TRIGGER {name} BEFORE {verb.upper()} ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION aurelis_refuse_write()"
            )


def install_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Install the triggers for the connection's dialect. Idempotent."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no invariant triggers written for dialect {dialect!r}. "
            "Aurelis will not run without them: append-only is a guarantee, "
            "not a best effort."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return expected_trigger_names()


def _installed_trigger_names(connection: sa.Connection) -> set[str]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
    elif dialect == "postgresql":
        rows = connection.execute(
            sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        )
    else:  # pragma: no cover - guarded by install_invariants
        raise NotImplementedError(dialect)
    return {str(row[0]) for row in rows}


def verify_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Return the expected triggers that are **missing**.

    Empty means the database is protected. Reported by ``aurelis doctor``
    rather than raised, because an operator needs to be told what to repair.
    """
    installed = _installed_trigger_names(connection)
    return tuple(name for name in expected_trigger_names() if name not in installed)
