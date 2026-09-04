"""The agent loop.

Every agent in the company is driven by the same seven steps:

.. code-block:: text

    wake        a task was assigned, or the scheduler fired
    orient      build the VIEW -- permissions decide what it sees
    recall      pull relevant memory (arrives with M6)
    act         reason, then produce an artifact or call a tool
    record      artifact, events and cost, in one transaction
    communicate post, answer, escalate
    sleep

Steps 2 and 5 hold the invariants. An agent cannot see outside its resolved
read scope because the runtime builds the view, and cannot write outside its
write scope because the database refuses the row.

**Budget is checked before the work, not after.** An agent whose daily
allowance is exhausted has its task refused at dispatch and recorded as
``REFUSED_BUDGET`` — a legitimate terminal outcome, not a crash.

The loop itself is deliberately thin. What an agent *does* with its turn is a
handler registered per task kind, so a new kind of work is a new handler rather
than a new branch in here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from aurelis.agents.roster import Roster, StaffedAgent
from aurelis.agents.tables import AgentState
from aurelis.agents.tools import ToolBox
from aurelis.agents.views import ViewContext
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, BudgetPeriod, BudgetScope, EventKind
from aurelis.core.errors import PermissionDenied
from aurelis.platform.budget.ledger import BudgetEnvelope, BudgetLedger, Spend
from aurelis.platform.db.tables import Task
from aurelis.platform.ledger.ledger import Ledger
from aurelis.platform.queue.queue import TaskQueue

if TYPE_CHECKING:
    from aurelis.comms.channels import Comms
    from aurelis.platform.artifacts.store import ArtifactStore
    from aurelis.platform.llm.cache import CachingProvider

__all__ = ["AgentContext", "AgentWorker", "TurnResult", "handler_for", "register_handler"]


@dataclass
class AgentContext:
    """Everything an agent's handler is allowed to reach.

    Deliberately explicit. A handler that could reach the whole runtime could
    reach around the permission model, so it gets the agent, the task, the
    session, and gated accessors — nothing else.
    """

    session: Session
    agent: StaffedAgent
    task: Task
    clock: Clock
    tools: ToolBox
    comms: Comms
    artifacts: ArtifactStore
    provider: CachingProvider
    ledger: Ledger
    envelope: BudgetEnvelope

    def view(self, view: Any, **params: Any) -> dict[str, Any]:
        """Build a permitted view. Refuses anything the charters do not grant."""
        from aurelis.agents.views import build_view

        return build_view(
            self.session,
            view,
            ViewContext(
                agent_ref=self.agent.ref,
                desk=self.agent.desk.value if self.agent.desk else None,
                task_ref=self.task.ref,
                subject=self.task.subject,
                params=params,
            ),
            self.agent.authority.read_views,
        )

    def use(self, scope: Any, **arguments: Any) -> Any:
        """Invoke a tool through the gate."""
        return self.tools.invoke(
            self.session,
            agent_ref=self.agent.ref,
            scope=scope,
            arguments=arguments,
            permitted=self.agent.authority.tools,
            task_ref=self.task.ref,
        )


@dataclass(frozen=True)
class TurnResult:
    """What an agent produced this turn."""

    summary: str
    artifact_digest: str | None = None
    spend: Spend = field(default_factory=Spend)
    produced: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[AgentContext], TurnResult]

_HANDLERS: dict[str, Handler] = {}


def register_handler(task_kind: str) -> Callable[[Handler], Handler]:
    """Bind a handler to a task kind. One handler per kind."""

    def decorate(fn: Handler) -> Handler:
        if task_kind in _HANDLERS:
            raise ValueError(f"task kind {task_kind!r} already has a handler")
        _HANDLERS[task_kind] = fn
        return fn

    return decorate


def handler_for(task_kind: str) -> Handler | None:
    return _HANDLERS.get(task_kind)


class AgentWorker:
    """Drives one agent through one turn at a time."""

    __slots__ = (
        "_artifacts",
        "_budget",
        "_clock",
        "_comms",
        "_ledger",
        "_provider",
        "_queue",
        "_roster",
        "_tools",
    )

    def __init__(
        self,
        *,
        roster: Roster,
        queue: TaskQueue,
        budget: BudgetLedger,
        tools: ToolBox,
        comms: Comms,
        artifacts: ArtifactStore,
        provider: CachingProvider,
        ledger: Ledger,
        clock: Clock | None = None,
    ) -> None:
        self._roster = roster
        self._queue = queue
        self._budget = budget
        self._tools = tools
        self._comms = comms
        self._artifacts = artifacts
        self._provider = provider
        self._ledger = ledger
        self._clock = clock or SystemClock()

    def envelope_for(self, agent: StaffedAgent, *, at: dt.datetime) -> BudgetEnvelope:
        """The budget scopes this agent's work counts against.

        The agent-day scope is what makes "this agent has spent its allowance
        for today" expressible without inventing a new mechanism: it is just a
        daily budget whose scope id is the agent and the date.
        """
        from aurelis.runtime import COMPANY_SCOPE_ID

        return BudgetEnvelope(
            company=COMPANY_SCOPE_ID,
            department=agent.department.value,
            agent_day=f"{agent.ref}:{at.date().isoformat()}",
        )

    def open_daily_budget(
        self,
        session: Session,
        agent: StaffedAgent,
        *,
        tokens: int,
        usd: Decimal = Decimal("0"),
        at: dt.datetime | None = None,
    ) -> None:
        moment = at or self._clock.now()
        self._budget.open(
            session,
            scope=BudgetScope.AGENT_DAY,
            scope_id=f"{agent.ref}:{moment.date().isoformat()}",
            tokens=tokens,
            usd=usd,
            period=BudgetPeriod.DAILY,
            at=moment,
        )

    def run_once(
        self, session: Session, agent: StaffedAgent, *, at: dt.datetime | None = None
    ) -> TurnResult | None:
        """Claim one task for ``agent`` and work it. ``None`` if nothing to do."""
        moment = at or self._clock.now()

        if agent.state is not AgentState.ACTIVE:
            return None

        task = self._queue.claim(
            session, worker=agent.ref, assignee=agent.ref, at=moment
        )
        if task is None:
            return None

        handler = handler_for(task.kind)
        if handler is None:
            self._queue.fail(
                session,
                task,
                reason=f"no handler registered for task kind {task.kind!r}",
                at=moment,
            )
            return None

        # The envelope the task was dispatched under, plus this agent's own
        # daily allowance. Both bind: a project can exhaust itself, and so can
        # an agent that has had a busy day inside a healthy project.
        envelope = self.envelope_for(agent, at=moment).merge(
            BudgetEnvelope.from_scopes(task.budget_envelope or {})
        )
        allowance = Spend(
            Decimal(task.allowance_usd or 0), int(task.allowance_tokens or 0)
        )
        if not allowance.is_zero:
            decision = self._budget.check(session, envelope, allowance, at=moment)
            if not decision.allowed:
                self._queue.fail(session, task, reason=decision.describe(), at=moment)
                self._ledger.append(
                    session,
                    kind=EventKind.BUDGET_EXHAUSTED,
                    actor=agent.ref,
                    subject=task.ref,
                    payload={
                        "bound_by": decision.bound_by.value if decision.bound_by else None,
                        "scope_id": decision.bound_scope_id,
                        "reason": decision.describe(),
                    },
                    at=moment,
                )
                return None

        context = AgentContext(
            session=session,
            agent=agent,
            task=task,
            clock=self._clock,
            tools=self._tools,
            comms=self._comms,
            artifacts=self._artifacts,
            provider=self._provider,
            ledger=self._ledger,
            envelope=envelope,
        )

        try:
            result = handler(context)
        except PermissionDenied as denial:
            # Already recorded by the gate that raised it; the task fails
            # terminally because an agent reaching outside its scope has told
            # us something, and retrying would erase it.
            self._queue.fail(session, task, reason=str(denial), at=moment)
            return None
        except Exception as error:
            self._queue.fail(
                session, task, reason=f"{type(error).__name__}: {error}", at=moment
            )
            raise

        if not result.spend.is_zero:
            self._budget.record(
                session,
                envelope,
                result.spend,
                actor=agent.ref,
                reason=task.kind,
                task_ref=task.ref,
                at=moment,
            )

        self._queue.succeed(session, task, result_digest=result.artifact_digest, at=moment)
        return result

    def run_all(self, session: Session, *, at: dt.datetime | None = None) -> list[TurnResult]:
        """Give every active agent one turn. The company's tick."""
        moment = at or self._clock.now()
        results: list[TurnResult] = []
        for agent in self._roster.workable(session):
            outcome = self.run_once(session, agent, at=moment)
            if outcome is not None:
                results.append(outcome)
        if results:
            self._ledger.append(
                session,
                kind=EventKind.AGENT_STATE_CHANGED,
                actor=Actor.SYSTEM,
                payload={"turns_completed": len(results)},
                at=moment,
            )
        return results
