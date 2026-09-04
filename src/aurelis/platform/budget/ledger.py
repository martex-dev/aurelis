"""Budgets, and the cost ledger they are checked against.

Budgets are **hard and checked at dispatch** — before a model is called, not
after the money is spent. A refusal is recorded as an event and returned to the
caller rather than raised, because running out of budget is a legitimate
terminal state for a line of work, not a crash. A mission that stopped because
it could not afford to continue has learned something about the question's
cost, and the record should say so.

**Two currencies.** Money and tokens are budgeted separately because they are
separately scarce. Under the Claude subscription the money figure is zero and
the token allowance is what binds; under a metered API it is the other way
round. Both are checked, and a refusal names which one ran out.

**The hierarchy** is ``company → department → mission → project → agent_day``.
A check walks it outermost-first and reports the **innermost** level that
bound, because "refused: over budget" tells an operator nothing they can act on
while "refused: PRJ-0012 has $0.03 of its $0.50 left, though the company has
$8 left" tells them which knob to turn.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import (
    BUDGET_SCOPE_ORDER,
    Actor,
    BudgetOutcome,
    BudgetPeriod,
    BudgetScope,
    EventKind,
)
from aurelis.core.ids import uuid7
from aurelis.platform.db.tables import Budget, CostEntry
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["BudgetDecision", "BudgetEnvelope", "BudgetLedger", "Spend"]

_SCOPE_COLUMN = {
    BudgetScope.COMPANY: CostEntry.company_id,
    BudgetScope.DEPARTMENT: CostEntry.department_id,
    BudgetScope.MISSION: CostEntry.mission_id,
    BudgetScope.PROJECT: CostEntry.project_id,
    BudgetScope.AGENT_DAY: CostEntry.agent_day_id,
}


@dataclass(frozen=True)
class Spend:
    """An amount of resource, in both currencies."""

    usd: Decimal = Decimal("0")
    tokens: int = 0

    def __add__(self, other: Spend) -> Spend:
        return Spend(self.usd + other.usd, self.tokens + other.tokens)

    @property
    def is_zero(self) -> bool:
        return self.usd == 0 and self.tokens == 0


@dataclass(frozen=True)
class BudgetEnvelope:
    """Which scopes a piece of work counts against.

    Every level present is checked. Levels the caller cannot name are simply
    absent — a platform task with no mission is checked against the company
    only, which is correct rather than a gap.
    """

    company: str | None = "company"
    department: str | None = None
    mission: str | None = None
    project: str | None = None
    agent_day: str | None = None

    def scope_ids(self) -> dict[BudgetScope, str]:
        pairs = {
            BudgetScope.COMPANY: self.company,
            BudgetScope.DEPARTMENT: self.department,
            BudgetScope.MISSION: self.mission,
            BudgetScope.PROJECT: self.project,
            BudgetScope.AGENT_DAY: self.agent_day,
        }
        return {scope: value for scope, value in pairs.items() if value}


@dataclass(frozen=True)
class BudgetDecision:
    """The answer to "may this be spent?", and why."""

    outcome: BudgetOutcome
    bound_by: BudgetScope | None = None
    bound_scope_id: str | None = None
    currency: str | None = None
    remaining: Spend | None = None
    requested: Spend = field(default_factory=Spend)

    @property
    def allowed(self) -> bool:
        return self.outcome is BudgetOutcome.ALLOWED

    def describe(self) -> str:
        if self.allowed:
            return "allowed"
        assert self.remaining is not None
        if self.currency == "usd":
            return (
                f"refused: {self.bound_by} {self.bound_scope_id} has "
                f"${self.remaining.usd} left and ${self.requested.usd} was requested"
            )
        return (
            f"refused: {self.bound_by} {self.bound_scope_id} has "
            f"{self.remaining.tokens} tokens left and {self.requested.tokens} was requested"
        )


class BudgetLedger:
    """Opens allowances, checks them, and records what was spent."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # ------------------------------------------------------------- opening

    def open(
        self,
        session: Session,
        *,
        scope: BudgetScope,
        scope_id: str,
        usd: Decimal | str = Decimal("0"),
        tokens: int = 0,
        period: BudgetPeriod = BudgetPeriod.LIFETIME,
        at: dt.datetime | None = None,
    ) -> Budget:
        """Create or return the allowance for one scope and window.

        Re-opening an existing window returns the existing row untouched. A
        budget that silently reset when someone re-ran a setup command would
        make every spend figure meaningless.
        """
        moment = at or self._clock.now()
        window = self._period_key(period, moment)
        existing = session.execute(
            sa.select(Budget).where(
                Budget.scope == scope.value,
                Budget.scope_id == scope_id,
                Budget.period_key == window,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        budget = Budget(
            budget_id=uuid7(),
            scope=scope.value,
            scope_id=scope_id,
            period=period.value,
            period_key=window,
            limit_usd=Decimal(usd),
            limit_tokens=tokens,
            created_at=moment,
        )
        session.add(budget)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.BUDGET_OPENED,
            subject=scope_id,
            payload={
                "scope": scope.value,
                "period": period.value,
                "period_key": window,
                "limit_usd": str(budget.limit_usd),
                "limit_tokens": tokens,
            },
            at=moment,
        )
        return budget

    @staticmethod
    def _period_key(period: BudgetPeriod, moment: dt.datetime) -> str:
        if period is BudgetPeriod.LIFETIME:
            return ""
        if period is BudgetPeriod.DAILY:
            return moment.date().isoformat()
        if period is BudgetPeriod.WEEKLY:
            year, week, _ = moment.isocalendar()
            return f"{year}-W{week:02d}"
        return moment.strftime("%Y-%m")

    # ------------------------------------------------------------ checking

    def spent(
        self,
        session: Session,
        scope: BudgetScope,
        scope_id: str,
        *,
        since: dt.datetime | None = None,
    ) -> Spend:
        """Total spend attributed to one scope."""
        column = _SCOPE_COLUMN[scope]
        query = sa.select(
            sa.func.coalesce(sa.func.sum(sa.cast(CostEntry.usd, sa.Numeric(24, 8))), 0),
            sa.func.coalesce(sa.func.sum(CostEntry.tokens_in + CostEntry.tokens_out), 0),
        ).where(column == scope_id)
        if since is not None:
            query = query.where(CostEntry.created_at >= since)
        usd, tokens = session.execute(query).one()
        return Spend(Decimal(str(usd)), int(tokens))

    def check(
        self,
        session: Session,
        envelope: BudgetEnvelope,
        requested: Spend,
        *,
        at: dt.datetime | None = None,
    ) -> BudgetDecision:
        """May ``requested`` be spent under ``envelope``?

        Walks outermost to innermost and returns the **last** level that
        refuses, so the message names the tightest binding constraint. A limit
        of zero means "no cap at this level", which is different from a cap of
        zero — an unmetered subscription sets money limits to zero and expects
        work to proceed.
        """
        moment = at or self._clock.now()
        refusal: BudgetDecision | None = None

        for scope in BUDGET_SCOPE_ORDER:
            scope_id = envelope.scope_ids().get(scope)
            if scope_id is None:
                continue
            budget = self._active_budget(session, scope, scope_id, moment)
            if budget is None:
                continue

            window_start = self._window_start(BudgetPeriod(budget.period), moment)
            used = self.spent(session, scope, scope_id, since=window_start)

            if budget.limit_usd > 0:
                remaining_usd = budget.limit_usd - used.usd
                if requested.usd > remaining_usd:
                    refusal = BudgetDecision(
                        outcome=BudgetOutcome.REFUSED,
                        bound_by=scope,
                        bound_scope_id=scope_id,
                        currency="usd",
                        remaining=Spend(remaining_usd, 0),
                        requested=requested,
                    )
            if budget.limit_tokens > 0:
                remaining_tokens = budget.limit_tokens - used.tokens
                if requested.tokens > remaining_tokens:
                    refusal = BudgetDecision(
                        outcome=BudgetOutcome.REFUSED,
                        bound_by=scope,
                        bound_scope_id=scope_id,
                        currency="tokens",
                        remaining=Spend(Decimal("0"), remaining_tokens),
                        requested=requested,
                    )

        return refusal or BudgetDecision(outcome=BudgetOutcome.ALLOWED, requested=requested)

    def _active_budget(
        self, session: Session, scope: BudgetScope, scope_id: str, moment: dt.datetime
    ) -> Budget | None:
        rows = session.execute(
            sa.select(Budget).where(Budget.scope == scope.value, Budget.scope_id == scope_id)
        ).scalars().all()
        for row in rows:
            period = BudgetPeriod(row.period)
            if row.period_key == self._period_key(period, moment):
                return row
        return None

    @staticmethod
    def _window_start(period: BudgetPeriod, moment: dt.datetime) -> dt.datetime | None:
        if period is BudgetPeriod.LIFETIME:
            return None
        if period is BudgetPeriod.DAILY:
            return moment.replace(hour=0, minute=0, second=0, microsecond=0)
        if period is BudgetPeriod.WEEKLY:
            day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
            return day - dt.timedelta(days=day.weekday())
        return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ------------------------------------------------------------ recording

    def record(
        self,
        session: Session,
        envelope: BudgetEnvelope,
        spend: Spend,
        *,
        actor: Actor | str = Actor.SYSTEM,
        reason: str,
        task_ref: str | None = None,
        at: dt.datetime | None = None,
    ) -> CostEntry:
        """Record spend against every scope in the envelope.

        Zero-cost work is recorded too. Under a subscription every model call
        costs zero dollars, and a ledger that skipped them would show a company
        that never did anything.
        """
        moment = at or self._clock.now()
        scopes = envelope.scope_ids()
        entry = CostEntry(
            entry_id=uuid7(),
            task_ref=task_ref,
            actor=str(actor),
            company_id=scopes.get(BudgetScope.COMPANY),
            department_id=scopes.get(BudgetScope.DEPARTMENT),
            mission_id=scopes.get(BudgetScope.MISSION),
            project_id=scopes.get(BudgetScope.PROJECT),
            agent_day_id=scopes.get(BudgetScope.AGENT_DAY),
            usd=spend.usd,
            tokens_in=0,
            tokens_out=spend.tokens,
            reason=reason,
            created_at=moment,
        )
        session.add(entry)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.BUDGET_SPENT,
            actor=actor,
            subject=task_ref,
            payload={
                "usd": str(spend.usd),
                "tokens": spend.tokens,
                "reason": reason,
                "scopes": {scope.value: value for scope, value in scopes.items()},
            },
            at=moment,
        )
        return entry
