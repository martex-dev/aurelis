"""A sealed thesis is immutable, and is scored once.

Two triggers, and together they are what makes "predicted before it happened"
a property of the database rather than a claim in a docstring.

**Nothing sealed may change.** The instrument, the horizon, the reference
close, the direction, the confidence, the words, the seal itself. A thesis
whose confidence could be nudged after the outcome is a thesis that can be
made to look calibrated, and calibration is the whole measure.

**A score is written once.** ``UPDATE`` may set the resolution columns only
while ``scored_at`` is null. Rescoring would let a bad prediction be quietly
improved once more became known — the same rule :mod:`aurelis.meetings.forecasts`
applies to meeting forecasts, now enforced below the application.

**Nothing is deleted.** A thesis that turned out wrong is the most valuable
row in the table.

The messages contain no apostrophe: they are embedded in SQL string literals.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = [
    "JUDGEMENT_TRIGGERS",
    "install_judgement_invariants",
    "verify_judgement_invariants",
]

JUDGEMENT_TRIGGERS: tuple[str, ...] = (
    "aurelis_thesis_seal_is_immutable",
    "aurelis_thesis_is_scored_once",
    "aurelis_thesis_is_never_deleted",
)

_SEALED_CHANGED = (
    "NEW.ref <> OLD.ref OR NEW.agent_ref <> OLD.agent_ref "
    "OR NEW.desk <> OLD.desk OR NEW.instrument <> OLD.instrument "
    "OR NEW.interval <> OLD.interval OR NEW.horizon_hours <> OLD.horizon_hours "
    "OR NEW.snapshot_ref <> OLD.snapshot_ref "
    "OR NEW.reference_at <> OLD.reference_at "
    "OR NEW.reference_close <> OLD.reference_close "
    "OR NEW.resolves_at <> OLD.resolves_at OR NEW.is_live <> OLD.is_live "
    "OR NEW.direction <> OLD.direction OR NEW.confidence <> OLD.confidence "
    "OR NEW.probability_up <> OLD.probability_up "
    "OR NEW.thesis <> OLD.thesis OR NEW.wrong_if <> OLD.wrong_if "
    "OR NEW.material_digest <> OLD.material_digest OR NEW.model <> OLD.model "
    "OR NEW.critic_ref IS NOT OLD.critic_ref "
    "OR NEW.attack_verdict IS NOT OLD.attack_verdict OR NEW.attack IS NOT OLD.attack "
    "OR NEW.confidence_stated IS NOT OLD.confidence_stated "
    "OR NEW.response IS NOT OLD.response "
    "OR NEW.response_because IS NOT OLD.response_because "
    "OR NEW.sealed_at <> OLD.sealed_at OR NEW.seal <> OLD.seal"
)

_SEALED = (
    "Aurelis: a sealed thesis cannot be changed. A prediction that can be "
    "edited after the outcome is not a prediction."
)
_SCORED = (
    "Aurelis: this thesis has already been scored. A score written twice lets "
    "a bad prediction be improved once more is known."
)
_DELETED = "Aurelis: a thesis is never deleted. The ones that were wrong are the record."


def _sqlite_statements() -> Iterator[str]:
    # Dropped and recreated rather than IF NOT EXISTS: the immutable column
    # list grew at M28, and a trigger kept from before that would have left
    # the new columns editable on every workspace made earlier.
    for name in JUDGEMENT_TRIGGERS:
        yield f"DROP TRIGGER IF EXISTS {name}"
    yield (
        "CREATE TRIGGER aurelis_thesis_seal_is_immutable "
        "BEFORE UPDATE ON theses FOR EACH ROW "
        f"WHEN ({_SEALED_CHANGED}) "
        f"BEGIN SELECT RAISE(ABORT, '{_SEALED}'); END"
    )
    yield (
        "CREATE TRIGGER aurelis_thesis_is_scored_once "
        "BEFORE UPDATE ON theses FOR EACH ROW "
        "WHEN OLD.scored_at IS NOT NULL "
        f"BEGIN SELECT RAISE(ABORT, '{_SCORED}'); END"
    )
    yield (
        "CREATE TRIGGER aurelis_thesis_is_never_deleted "
        "BEFORE DELETE ON theses FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_DELETED}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_thesis_guard() RETURNS trigger AS $$ "
        f"BEGIN IF ({_SEALED_CHANGED}) THEN RAISE EXCEPTION '{_SEALED}'; END IF; "
        f"IF OLD.scored_at IS NOT NULL THEN RAISE EXCEPTION '{_SCORED}'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_thesis_no_delete() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_DELETED}'; END; $$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_thesis_seal_is_immutable ON theses"
    yield (
        "CREATE TRIGGER aurelis_thesis_seal_is_immutable "
        "BEFORE UPDATE ON theses FOR EACH ROW EXECUTE FUNCTION aurelis_thesis_guard()"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_thesis_is_scored_once ON theses"
    yield (
        "CREATE TRIGGER aurelis_thesis_is_scored_once "
        "BEFORE UPDATE ON theses FOR EACH ROW EXECUTE FUNCTION aurelis_thesis_guard()"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_thesis_is_never_deleted ON theses"
    yield (
        "CREATE TRIGGER aurelis_thesis_is_never_deleted "
        "BEFORE DELETE ON theses FOR EACH ROW EXECUTE FUNCTION aurelis_thesis_no_delete()"
    )


def install_judgement_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Install the thesis guards. Idempotent."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no judgement invariants written for dialect {dialect!r}. Aurelis "
            "will not run without them: a sealed prediction that can be edited "
            "is the one thing that would make the forward record worthless."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return JUDGEMENT_TRIGGERS


def verify_judgement_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Return the expected triggers that are **missing**."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
    elif dialect == "postgresql":
        rows = connection.execute(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
    else:  # pragma: no cover - guarded by install
        raise NotImplementedError(dialect)
    installed = {str(row[0]) for row in rows}
    return tuple(name for name in JUDGEMENT_TRIGGERS if name not in installed)
