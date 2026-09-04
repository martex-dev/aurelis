"""Views: the entire world an agent sees for a piece of work.

This is the permission model that matters most for research quality, and it is
stronger than role-based access control in one specific way: **a view is
built, not filtered**. An agent does not receive the company's state with some
fields removed; it receives a small object assembled for its task. There is no
"rest of the object" to leak.

The reason is not secrecy, it is validity. An agent told which features moved
does not need to run the experiment. A critic that has already seen the
author's conclusion is reviewing a conclusion rather than evidence. Narrow
views are what make the research real.

Registering a view is the only way to widen what a charter can look at, so
"what did the Strategy Critic know when it signed off?" is answered by reading
a registry rather than tracing call sites.

Views are also the prompt. An agent's context *is* its view, which is why
thin views are simultaneously the main cost control — see ADR-0007.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.errors import PermissionDenied
from aurelis.org.scopes import ReadView

__all__ = ["ViewContext", "ViewRegistry", "build_view", "register_view", "registered_views"]


@dataclass(frozen=True, slots=True)
class ViewContext:
    """What the builder is allowed to know about the request."""

    agent_ref: str
    desk: str | None = None
    task_ref: str | None = None
    subject: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


ViewBuilder = Callable[[Session, ViewContext], dict[str, Any]]

_BUILDERS: dict[ReadView, ViewBuilder] = {}


def register_view(view: ReadView) -> Callable[[ViewBuilder], ViewBuilder]:
    """Register the builder for a view. One builder per view, ever."""

    def decorate(builder: ViewBuilder) -> ViewBuilder:
        if view in _BUILDERS:
            raise ValueError(
                f"view {view} already has a builder ({_BUILDERS[view].__name__}). "
                "One builder per view: two would mean two different answers to "
                "'what does this role see?'"
            )
        _BUILDERS[view] = builder
        return builder

    return decorate


def registered_views() -> frozenset[ReadView]:
    return frozenset(_BUILDERS)


def build_view(
    session: Session,
    view: ReadView,
    context: ViewContext,
    permitted: frozenset[ReadView],
) -> dict[str, Any]:
    """Build ``view`` for an agent, refusing if the charter does not grant it.

    The permission check happens here rather than at the call site, so there is
    exactly one place a view can be obtained and exactly one place it can be
    refused.
    """
    if view not in permitted and ReadView.EVERYTHING not in permitted:
        raise PermissionDenied(context.agent_ref, f"read {view.value}", context.subject or "-")
    builder = _BUILDERS.get(view)
    if builder is None:
        raise NotImplementedError(
            f"view {view} is granted to charters but has no builder yet. "
            "It lands with the layer that owns its data."
        )
    return builder(session, context)


class ViewRegistry:
    """Convenience wrapper binding a session and an agent's permissions."""

    __slots__ = ("_permitted", "_session")

    def __init__(self, session: Session, permitted: frozenset[ReadView]) -> None:
        self._session = session
        self._permitted = permitted

    def build(self, view: ReadView, context: ViewContext) -> dict[str, Any]:
        return build_view(self._session, view, context, self._permitted)


# ------------------------------------------------------------------ builders
#
# Only the views M1 actually needs. The rest land with the layers that own
# their data, and asking for one before then raises NotImplementedError rather
# than returning a plausible empty dict -- an agent reasoning over a silently
# empty view is worse than one that fails.


@register_view(ReadView.COMPANY_STATE)
def _company_state(session: Session, context: ViewContext) -> dict[str, Any]:
    from aurelis.agents.tables import Agent
    from aurelis.org.tables import OrgDesk

    headcount = session.execute(sa.select(sa.func.count()).select_from(Agent)).scalar_one()
    desks = session.execute(
        sa.select(OrgDesk.desk_id).where(OrgDesk.status == "active")
    ).scalars().all()
    return {
        "headcount": int(headcount),
        "active_desks": sorted(desks),
        "milestone": "M1",
    }


@register_view(ReadView.TASK_ASSIGNMENT)
def _task_assignment(session: Session, context: ViewContext) -> dict[str, Any]:
    from aurelis.platform.db.tables import Task

    if context.task_ref is None:
        return {"task": None}
    task = session.execute(
        sa.select(Task).where(Task.ref == context.task_ref)
    ).scalar_one_or_none()
    if task is None:
        return {"task": None}
    return {
        "task": task.ref,
        "kind": task.kind,
        "subject": task.subject,
        "payload": task.payload,
    }


@register_view(ReadView.DESK_MARKET_SNAPSHOT)
def _desk_snapshot(session: Session, context: ViewContext) -> dict[str, Any]:
    """The desk's most recent bars, as measured values.

    Deliberately not "the market". A snapshot the agent is told about, with the
    source and the digest it came from, so anything the agent says about it can
    be checked against what it was actually shown.
    """
    from aurelis.intel.sources import snapshot_for

    if context.desk is None:
        return {"desk": None, "bars": []}
    return snapshot_for(context.desk, context.params.get("symbol"))


@register_view(ReadView.DESK_OBSERVATIONS)
def _desk_observations(session: Session, context: ViewContext) -> dict[str, Any]:
    from aurelis.intel.tables import MarketObservation

    rows = (
        session.execute(
            sa.select(MarketObservation)
            .where(MarketObservation.desk == (context.desk or ""))
            .order_by(MarketObservation.as_of.desc())
            .limit(int(context.params.get("limit", 10)))
        )
        .scalars()
        .all()
    )
    return {
        "desk": context.desk,
        "observations": [
            {
                "ref": r.ref,
                "author": r.author,
                "kind": r.kind,
                "symbol": r.symbol,
                "statement": r.statement,
                "as_of": r.as_of.isoformat(),
                "source": r.source,
            }
            for r in rows
        ],
    }
