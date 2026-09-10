"""A data grant cannot be widened, only revoked.

The service fetches only what a grant names. A grant that could later be
edited to name more would let the one boundary that still needs a person be
crossed by whoever had the database open. So the vendor, the desk, the
instruments and the grantor are frozen from the moment the row exists, and
the only change the database accepts is a revocation written once.

The messages contain no apostrophe: they are embedded in SQL string literals.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["SERVICE_TRIGGERS", "install_service_invariants", "verify_service_invariants"]

SERVICE_TRIGGERS: tuple[str, ...] = (
    "aurelis_grant_is_immutable",
    "aurelis_grant_revoked_once",
    "aurelis_grant_never_deleted",
)

_CHANGED = (
    "NEW.ref <> OLD.ref OR NEW.source <> OLD.source OR NEW.desk <> OLD.desk "
    "OR NEW.instruments <> OLD.instruments OR NEW.interval <> OLD.interval "
    "OR NEW.bars <> OLD.bars OR NEW.granted_by <> OLD.granted_by "
    "OR NEW.granted_at <> OLD.granted_at OR NEW.reason <> OLD.reason"
)
_FROZEN = (
    "Aurelis: a data grant cannot be changed. The service fetches only what a "
    "person granted, and a grant that could be widened afterwards is a flag."
)
_REVOKED = "Aurelis: this grant was already revoked. A revocation is written once."
_DELETED = "Aurelis: a data grant is never deleted. Revoke it."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_grant_is_immutable "
        "BEFORE UPDATE ON data_grants FOR EACH ROW "
        f"WHEN ({_CHANGED}) BEGIN SELECT RAISE(ABORT, '{_FROZEN}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_grant_revoked_once "
        "BEFORE UPDATE ON data_grants FOR EACH ROW "
        "WHEN OLD.revoked_at IS NOT NULL "
        f"BEGIN SELECT RAISE(ABORT, '{_REVOKED}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_grant_never_deleted "
        "BEFORE DELETE ON data_grants FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_DELETED}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_grant_guard() RETURNS trigger AS $$ "
        f"BEGIN IF ({_CHANGED}) THEN RAISE EXCEPTION '{_FROZEN}'; END IF; "
        f"IF OLD.revoked_at IS NOT NULL THEN RAISE EXCEPTION '{_REVOKED}'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_grant_no_delete() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_DELETED}'; END; $$ LANGUAGE plpgsql"
    )
    for name in ("aurelis_grant_is_immutable", "aurelis_grant_revoked_once"):
        yield f"DROP TRIGGER IF EXISTS {name} ON data_grants"
        yield (
            f"CREATE TRIGGER {name} BEFORE UPDATE ON data_grants FOR EACH ROW "
            "EXECUTE FUNCTION aurelis_grant_guard()"
        )
    yield "DROP TRIGGER IF EXISTS aurelis_grant_never_deleted ON data_grants"
    yield (
        "CREATE TRIGGER aurelis_grant_never_deleted BEFORE DELETE ON data_grants "
        "FOR EACH ROW EXECUTE FUNCTION aurelis_grant_no_delete()"
    )


def install_service_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no service invariants written for dialect {dialect!r}. Aurelis will "
            "not run without them: a grant that can be widened is the one boundary "
            "that still needs a person, crossed."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return SERVICE_TRIGGERS


def verify_service_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
    elif dialect == "postgresql":
        rows = connection.execute(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
    else:  # pragma: no cover - guarded by install
        raise NotImplementedError(dialect)
    installed = {str(row[0]) for row in rows}
    return tuple(name for name in SERVICE_TRIGGERS if name not in installed)
