"""A stated mechanism is immutable; only its retirement may be written.

The claim, the pattern, the confidence and the decay model are frozen from the
moment the mechanism exists. The one change the database accepts is a
retirement, written once — a mechanism whose out-of-sample predictions turned
out to be noise is killed, not deleted, because the graveyard of failed
mechanisms is what the company shows to prove it does not fool itself.

The messages contain no apostrophe: they are embedded in SQL string literals.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["MECHANISM_TRIGGERS", "install_mechanism_invariants", "verify_mechanism_invariants"]

MECHANISM_TRIGGERS: tuple[str, ...] = (
    "aurelis_mechanism_is_immutable",
    "aurelis_mechanism_never_deleted",
)

_CHANGED = (
    "NEW.ref IS NOT OLD.ref OR NEW.agent_ref IS NOT OLD.agent_ref "
    "OR NEW.title IS NOT OLD.title OR NEW.trigger_kind IS NOT OLD.trigger_kind "
    "OR NEW.desk IS NOT OLD.desk OR NEW.horizon_hours IS NOT OLD.horizon_hours "
    "OR NEW.direction IS NOT OLD.direction OR NEW.confidence IS NOT OLD.confidence "
    "OR NEW.why IS NOT OLD.why OR NEW.other_side IS NOT OLD.other_side "
    "OR NEW.decay IS NOT OLD.decay OR NEW.origin IS NOT OLD.origin "
    "OR NEW.found_on_instrument IS NOT OLD.found_on_instrument "
    "OR NEW.found_on_event IS NOT OLD.found_on_event OR NEW.seal IS NOT OLD.seal "
    "OR NEW.stated_at IS NOT OLD.stated_at"
)
_FROZEN = (
    "Aurelis: a stated mechanism cannot be changed. A mechanism that could be "
    "edited after its predictions came in is one fitted to its own results."
)
_DELETED = "Aurelis: a mechanism is never deleted. Retire it; the graveyard is the record."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_mechanism_is_immutable "
        "BEFORE UPDATE ON mechanisms FOR EACH ROW "
        f"WHEN ({_CHANGED}) BEGIN SELECT RAISE(ABORT, '{_FROZEN}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_mechanism_never_deleted "
        "BEFORE DELETE ON mechanisms FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_DELETED}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_mechanism_guard() RETURNS trigger AS $$ "
        f"BEGIN IF ({_CHANGED}) THEN RAISE EXCEPTION '{_FROZEN}'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_mechanism_no_delete() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_DELETED}'; END; $$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_mechanism_is_immutable ON mechanisms"
    yield (
        "CREATE TRIGGER aurelis_mechanism_is_immutable BEFORE UPDATE ON mechanisms "
        "FOR EACH ROW EXECUTE FUNCTION aurelis_mechanism_guard()"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_mechanism_never_deleted ON mechanisms"
    yield (
        "CREATE TRIGGER aurelis_mechanism_never_deleted BEFORE DELETE ON mechanisms "
        "FOR EACH ROW EXECUTE FUNCTION aurelis_mechanism_no_delete()"
    )


def install_mechanism_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(f"no mechanism invariants written for dialect {dialect!r}")
    for statement in statements:
        connection.execute(sa.text(statement))
    return MECHANISM_TRIGGERS


def verify_mechanism_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
    elif dialect == "postgresql":
        rows = connection.execute(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
    else:  # pragma: no cover - guarded by install
        raise NotImplementedError(dialect)
    installed = {str(row[0]) for row in rows}
    return tuple(name for name in MECHANISM_TRIGGERS if name not in installed)
