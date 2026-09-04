"""Projecting the code registry into the database.

Runs at ``db init`` and again whenever the code registry changes. Rebuild is a
full replace of the charter tables, because they are a projection and a
projection that drifts from its source is worse than no projection at all — the
write-scope triggers would be enforcing an org chart nobody had reviewed.

Desks are different: their **status** genuinely changes at runtime, by Board
decision. So a desk row is inserted once and its status left alone afterwards.
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import sha256_of
from aurelis.org.charters import CHARTERS
from aurelis.org.desks import DESKS
from aurelis.org.tables import (
    CharterReadView,
    CharterTool,
    CharterWriteScope,
    OrgCharter,
    OrgDesk,
)

__all__ = ["registry_fingerprint", "seed_org", "stored_fingerprint"]


def registry_fingerprint() -> str:
    """A hash of the whole org chart as it exists in code.

    Compared against what the database was seeded from, so ``aurelis doctor``
    can say "the charters in code have changed since this workspace was
    seeded" rather than leaving the triggers to enforce a stale org chart.
    """
    return sha256_of(
        [
            {
                "id": c.charter_id,
                "number": c.number,
                "department": c.department.value,
                "tier": c.tier.value,
                "seniority": c.seniority.value,
                "views": sorted(v.value for v in c.read_views),
                "scopes": sorted(s.value for s in c.write_scopes),
                "tools": sorted(t.value for t in c.tools),
            }
            for c in sorted(CHARTERS.values(), key=lambda c: c.number)
        ]
    )


def stored_fingerprint(session: Session) -> str:
    """The fingerprint of what is actually in the database right now."""
    rows = session.execute(
        sa.select(OrgCharter).order_by(OrgCharter.number)
    ).scalars().all()
    views: dict[str, list[str]] = {}
    scopes: dict[str, list[str]] = {}
    tools: dict[str, list[str]] = {}
    for cid, view in session.execute(sa.select(CharterReadView.charter_id, CharterReadView.view)):
        views.setdefault(cid, []).append(view)
    for cid, scope in session.execute(
        sa.select(CharterWriteScope.charter_id, CharterWriteScope.scope)
    ):
        scopes.setdefault(cid, []).append(scope)
    for cid, tool in session.execute(sa.select(CharterTool.charter_id, CharterTool.tool)):
        tools.setdefault(cid, []).append(tool)

    return sha256_of(
        [
            {
                "id": r.charter_id,
                "number": r.number,
                "department": r.department,
                "tier": r.tier,
                "seniority": r.seniority,
                "views": sorted(views.get(r.charter_id, [])),
                "scopes": sorted(scopes.get(r.charter_id, [])),
                "tools": sorted(tools.get(r.charter_id, [])),
            }
            for r in rows
        ]
    )


def seed_org(session: Session, *, now: dt.datetime) -> tuple[int, int]:
    """Rebuild the charter projection and register any new desks.

    Returns ``(charters, desks)`` written. Idempotent, and safe to run against
    a live workspace: agent coverage rows reference charter ids, and the ids
    are stable, so a rebuild never disturbs who holds what.
    """
    if stored_fingerprint(session) == registry_fingerprint():
        return (0, _seed_desks(session, now))

    # Full replace. The scope tables cascade from org_charters, but they are
    # cleared explicitly so the operation does not depend on the database
    # honouring ON DELETE CASCADE, which SQLite only does with the pragma set.
    session.execute(sa.delete(CharterWriteScope))
    session.execute(sa.delete(CharterReadView))
    session.execute(sa.delete(CharterTool))
    session.execute(sa.delete(OrgCharter))
    session.flush()

    ordered = sorted(CHARTERS.values(), key=lambda c: c.number)

    # Parents first, flushed, then children. SQLAlchemy's unit of work orders
    # inserts by ORM *relationships*, and these tables are linked only by raw
    # foreign keys -- so without this flush the scope rows are attempted before
    # the charters they reference and the FK refuses them. Declaring
    # relationships purely to get insert ordering would add a graph of
    # back-references nothing else needs.
    for spec in ordered:
        session.add(
            OrgCharter(
                charter_id=spec.charter_id,
                number=spec.number,
                name=spec.name,
                department=spec.department.value,
                remit=spec.remit,
                tier=spec.tier.value,
                seniority=spec.seniority.value,
                desk_specific=spec.desk_specific,
                deterministic=spec.deterministic,
            )
        )
    session.flush()

    for spec in ordered:
        for view in spec.read_views:
            session.add(CharterReadView(charter_id=spec.charter_id, view=view.value))
        for scope in spec.write_scopes:
            session.add(CharterWriteScope(charter_id=spec.charter_id, scope=scope.value))
        for tool in spec.tools:
            session.add(CharterTool(charter_id=spec.charter_id, tool=tool.value))
    session.flush()

    return (len(CHARTERS), _seed_desks(session, now))


def _seed_desks(session: Session, now: dt.datetime) -> int:
    """Insert desks that do not exist yet. Never overwrites a status."""
    existing = set(session.execute(sa.select(OrgDesk.desk_id)).scalars())
    written = 0
    for desk, spec in DESKS.items():
        if desk.value in existing:
            continue
        session.add(
            OrgDesk(
                desk_id=desk.value,
                name=spec.name,
                status=spec.status.value,
                instruments=",".join(spec.instruments),
                engines=",".join(spec.engines),
                calendar=spec.calendar,
                opens_at_milestone=spec.opens_at_milestone,
            )
        )
        written += 1
    session.flush()
    return written
