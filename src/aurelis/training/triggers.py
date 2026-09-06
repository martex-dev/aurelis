"""The onboarding gate, enforced by the database.

"An agent that cannot catch planted defects in its own specialty does not start
work" is worth nothing as a rule inside :mod:`aurelis.training.onboarding`. Any
other code path, any migration, any SQL console gets around it — and the path
that matters most is the ordinary one: ``Roster.set_state(ref, ACTIVE)``, which
knows nothing about training.

So it is a trigger. An ``agents`` row may not move into ``active`` while its
most recent training run says ``failed``. Two properties follow that a
service-layer check would not have:

**A failure is not fixed by retrying the state change.** It is fixed by running
the suite again and scoring better, because the trigger reads the latest run
rather than any flag.

**Absence of a record does not block.** An agent the suite never questioned is
not one it found wanting. Requiring a run before activation would make the
company un-staffable the moment a charter fell outside the catalogue, and would
dress a gap in the scenarios up as a judgement about a person.

This is a ``BEFORE UPDATE`` guard, the first in the system — every other
invariant here guards inserts. State lives in an UPDATE, so that is where the
guard has to be.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = [
    "TRAINING_TRIGGERS",
    "install_training_invariants",
    "verify_training_invariants",
]

TRAINING_TRIGGERS: tuple[str, ...] = ("aurelis_agent_may_not_work_while_failed",)

_MESSAGE = (
    "Aurelis: agent may not become active -- its most recent training run "
    "failed. An agent that cannot catch planted defects in its own specialty "
    "does not start work (ADR-0005)."
)

_LATEST_VERDICT = (
    "SELECT t.verdict FROM training_runs t WHERE t.agent_ref = NEW.ref "
    "ORDER BY t.measured_at DESC, t.ref DESC LIMIT 1"
)


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_agent_may_not_work_while_failed "
        "BEFORE UPDATE OF state ON agents FOR EACH ROW "
        "WHEN NEW.state IN ('active','working','in_meeting') "
        f"AND ({_LATEST_VERDICT}) = 'failed' "
        f"BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_onboarding() RETURNS trigger AS $$ "
        "DECLARE latest text; BEGIN "
        "IF NEW.state NOT IN ('active','working','in_meeting') THEN RETURN NEW; END IF; "
        "SELECT t.verdict INTO latest FROM training_runs t "
        "WHERE t.agent_ref = NEW.ref ORDER BY t.measured_at DESC, t.ref DESC LIMIT 1; "
        "IF latest = 'failed' THEN RAISE EXCEPTION "
        f"'{_MESSAGE}'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "DROP TRIGGER IF EXISTS aurelis_agent_may_not_work_while_failed ON agents"
    )
    yield (
        "CREATE TRIGGER aurelis_agent_may_not_work_while_failed "
        "BEFORE UPDATE OF state ON agents FOR EACH ROW "
        "EXECUTE FUNCTION aurelis_check_onboarding()"
    )


def install_training_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Install the onboarding gate. Idempotent."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no onboarding gate written for dialect {dialect!r}. Aurelis will "
            "not run without it: who may start work is a guarantee, not a "
            "best effort."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return TRAINING_TRIGGERS


def verify_training_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Return the expected triggers that are **missing**."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
    elif dialect == "postgresql":
        rows = connection.execute(
            sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        )
    else:  # pragma: no cover - guarded by install
        raise NotImplementedError(dialect)
    installed = {str(row[0]) for row in rows}
    return tuple(name for name in TRAINING_TRIGGERS if name not in installed)
