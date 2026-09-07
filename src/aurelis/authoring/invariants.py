"""A search budget, frozen by the database once the search has started.

One trigger, and it is the whole stopping rule made real.

**A campaign plan may not be edited once an attempt has run.** The budget, the
declared width and the criterion are fixed before the first design exists.
After that they are frozen, exactly as a research preregistration is
(ADR-0012) and an org change's prediction is. A budget that could be raised
after seeing the results is not a budget, it is a description of what happened;
and a criterion rewritten once the numbers are in is the HARKing that the whole
research lifecycle exists to make unreachable.

This is enforced here rather than in :mod:`aurelis.authoring.campaign` for the
same reason every other invariant in this repository is: application code is
one migration, one console session or one new code path away from being
bypassed, and a stopping rule that can be stepped around is not a stopping
rule.

The message must contain no apostrophe. It is embedded in a SQL string literal
and one would end it -- the mistake that broke ``CREATE TRIGGER`` at M11.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = [
    "AUTHORING_TRIGGERS",
    "install_authoring_invariants",
    "verify_authoring_invariants",
]

AUTHORING_TRIGGERS: tuple[str, ...] = ("aurelis_campaign_plan_is_immutable",)

_FROZEN = (
    "Aurelis: this campaign has already run an attempt, so its budget, width "
    "and criterion are frozen. A budget raised after seeing the results is not "
    "a budget, it is a description of what happened."
)

_PLAN_CHANGED = (
    "NEW.budget <> OLD.budget "
    "OR NEW.declared_width <> OLD.declared_width "
    "OR NEW.criterion <> OLD.criterion "
    "OR NEW.plan_digest <> OLD.plan_digest"
)


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_campaign_plan_is_immutable "
        "BEFORE UPDATE ON authoring_campaigns FOR EACH ROW "
        f"WHEN OLD.attempts_run > 0 AND ({_PLAN_CHANGED}) "
        f"BEGIN SELECT RAISE(ABORT, '{_FROZEN}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_campaign_plan_frozen() RETURNS trigger AS $$ "
        f"BEGIN IF OLD.attempts_run > 0 AND ({_PLAN_CHANGED}) "
        f"THEN RAISE EXCEPTION '{_FROZEN}'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "DROP TRIGGER IF EXISTS aurelis_campaign_plan_is_immutable "
        "ON authoring_campaigns"
    )
    yield (
        "CREATE TRIGGER aurelis_campaign_plan_is_immutable "
        "BEFORE UPDATE ON authoring_campaigns FOR EACH ROW "
        "EXECUTE FUNCTION aurelis_campaign_plan_frozen()"
    )


def install_authoring_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Install the campaign guard. Idempotent."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no authoring invariants written for dialect {dialect!r}. Aurelis "
            "will not run without them: a search budget that can be raised "
            "mid-search is the whole failure this milestone exists to prevent."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return AUTHORING_TRIGGERS


def verify_authoring_invariants(connection: sa.Connection) -> tuple[str, ...]:
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
    return tuple(name for name in AUTHORING_TRIGGERS if name not in installed)
