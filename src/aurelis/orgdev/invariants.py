"""Coverage conservation, and the locked prediction — both in the database.

Four triggers, and the first two are the ones ADR-0003's guarantee actually
rests on.

**A charter may not be orphaned.** Deleting the last remaining holder of a
charter is refused. This is stronger than it looks, because ``agent_coverage``
cascades from ``agents``: retiring an agent that still holds a charter tries to
delete its coverage rows, the cascade fires this trigger, and the whole
retirement is refused. Handover is therefore not a convention that fission
follows — it is the only way to remove somebody from the company.

**An agent may not be retired while it holds coverage.** The same guarantee
said forwards, so the error message names the real problem rather than
surfacing as a cascade failure three tables away.

**A locked prediction may not be edited.** An ``OrgChange`` hashes its
predicted metric, direction, magnitude and measurement plan before the room
sees it. After that the columns are frozen, exactly as a research
preregistration is (ADR-0012). A prediction that can be re-aimed once the
outcome is known is not a prediction.

**A change may not be applied before it was decided.** The state machine lives
in :mod:`aurelis.orgdev.development`, but "somebody edited the org chart
without a meeting" is the failure worth making impossible rather than unlikely.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = [
    "ORG_TRIGGERS",
    "install_org_invariants",
    "verify_org_invariants",
]

ORG_TRIGGERS: tuple[str, ...] = (
    "aurelis_coverage_may_not_be_orphaned",
    "aurelis_agent_may_not_retire_holding_coverage",
    "aurelis_locked_prediction_is_immutable",
    "aurelis_org_change_applied_only_once_approved",
)

_ORPHAN = (
    "Aurelis: that is the last agent holding this charter. Coverage moves, it "
    "is never dropped -- hand it over first (ADR-0003)."
)
_RETIRE = (
    "Aurelis: this agent still holds charters. Retiring it would orphan them; "
    "hand its coverage over first (ADR-0003)."
)
_LOCKED = (
    "Aurelis: this org change is locked. Its prediction and measurement plan "
    "were hashed before the room saw them, and a prediction that can be "
    "re-aimed after the outcome is not a prediction (ADR-0012)."
)
_UNDECIDED = (
    "Aurelis: an org change may only be applied once approved. A structural "
    "edit nobody decided on is not a decision."
)

_STILL_HELD = (
    "SELECT 1 FROM agent_coverage c "
    "WHERE c.charter_id = OLD.charter_id AND c.agent_ref <> OLD.agent_ref"
)

_PREDICTION_CHANGED = (
    "NEW.predicted_metric <> OLD.predicted_metric "
    "OR NEW.predicted_direction <> OLD.predicted_direction "
    "OR NEW.predicted_magnitude <> OLD.predicted_magnitude "
    "OR NEW.measurement_plan <> OLD.measurement_plan "
    "OR NEW.measure_after_days <> OLD.measure_after_days "
    "OR NEW.locked_digest <> OLD.locked_digest"
)


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_coverage_may_not_be_orphaned "
        "BEFORE DELETE ON agent_coverage FOR EACH ROW "
        f"WHEN NOT EXISTS ({_STILL_HELD}) "
        f"BEGIN SELECT RAISE(ABORT, '{_ORPHAN}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_agent_may_not_retire_holding_coverage "
        "BEFORE UPDATE OF state ON agents FOR EACH ROW "
        "WHEN NEW.state = 'retired' AND OLD.state <> 'retired' "
        "AND EXISTS (SELECT 1 FROM agent_coverage c WHERE c.agent_ref = NEW.ref) "
        f"BEGIN SELECT RAISE(ABORT, '{_RETIRE}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_locked_prediction_is_immutable "
        "BEFORE UPDATE ON org_changes FOR EACH ROW "
        f"WHEN OLD.locked_at IS NOT NULL AND ({_PREDICTION_CHANGED}) "
        f"BEGIN SELECT RAISE(ABORT, '{_LOCKED}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_org_change_applied_only_once_approved "
        "BEFORE UPDATE OF state ON org_changes FOR EACH ROW "
        "WHEN NEW.state = 'applied' AND OLD.state <> 'approved' "
        f"BEGIN SELECT RAISE(ABORT, '{_UNDECIDED}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_coverage_conserved() RETURNS trigger AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM agent_coverage c "
        "WHERE c.charter_id = OLD.charter_id AND c.agent_ref <> OLD.agent_ref) "
        f"THEN RAISE EXCEPTION '{_ORPHAN}'; END IF; RETURN OLD; END; $$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_coverage_may_not_be_orphaned ON agent_coverage"
    yield (
        "CREATE TRIGGER aurelis_coverage_may_not_be_orphaned "
        "BEFORE DELETE ON agent_coverage FOR EACH ROW "
        "EXECUTE FUNCTION aurelis_coverage_conserved()"
    )

    yield (
        "CREATE OR REPLACE FUNCTION aurelis_retire_needs_handover() RETURNS trigger AS $$ "
        "BEGIN IF NEW.state = 'retired' AND OLD.state <> 'retired' "
        "AND EXISTS (SELECT 1 FROM agent_coverage c WHERE c.agent_ref = NEW.ref) "
        f"THEN RAISE EXCEPTION '{_RETIRE}'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_agent_may_not_retire_holding_coverage ON agents"
    yield (
        "CREATE TRIGGER aurelis_agent_may_not_retire_holding_coverage "
        "BEFORE UPDATE OF state ON agents FOR EACH ROW "
        "EXECUTE FUNCTION aurelis_retire_needs_handover()"
    )

    yield (
        "CREATE OR REPLACE FUNCTION aurelis_prediction_frozen() RETURNS trigger AS $$ "
        f"BEGIN IF OLD.locked_at IS NOT NULL AND ({_PREDICTION_CHANGED}) "
        f"THEN RAISE EXCEPTION '{_LOCKED}'; END IF; "
        "IF NEW.state = 'applied' AND OLD.state <> 'approved' "
        f"THEN RAISE EXCEPTION '{_UNDECIDED}'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for name in (
        "aurelis_locked_prediction_is_immutable",
        "aurelis_org_change_applied_only_once_approved",
    ):
        yield f"DROP TRIGGER IF EXISTS {name} ON org_changes"
        yield (
            f"CREATE TRIGGER {name} BEFORE UPDATE ON org_changes FOR EACH ROW "
            "EXECUTE FUNCTION aurelis_prediction_frozen()"
        )


def install_org_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Install the coverage and preregistration guards. Idempotent.

    The messages below must not contain an apostrophe: they are embedded in a
    SQL string literal, and one would end it. A single quotation mark in the
    word "approved" is what caught this the first time.
    """
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no org invariants written for dialect {dialect!r}. Aurelis will "
            "not run without them: coverage conservation is the guarantee the "
            "whole growth mechanism rests on."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return ORG_TRIGGERS


def verify_org_invariants(connection: sa.Connection) -> tuple[str, ...]:
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
    return tuple(name for name in ORG_TRIGGERS if name not in installed)
