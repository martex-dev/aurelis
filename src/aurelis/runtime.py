"""The composition root.

One object that wires the platform together, so nothing else has to know the
construction order. Every component takes its collaborators as arguments —
that is what makes them testable — and this is the single place that decides
which concrete ones they get.

Held deliberately thin. When the corporation's own layers arrive they get their
own roots; this one owns the platform and nothing above it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aurelis import __version__
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.config import Settings, load_settings
from aurelis.core.enums import Actor, BudgetPeriod, BudgetScope, EventKind
from aurelis.platform.artifacts.store import ArtifactStore
from aurelis.platform.budget.ledger import BudgetLedger
from aurelis.platform.db.session import Database
from aurelis.platform.ledger.ledger import Ledger
from aurelis.platform.llm.cache import CachingProvider
from aurelis.platform.llm.factory import build_provider
from aurelis.platform.llm.providers import ModelProvider
from aurelis.platform.queue.queue import TaskQueue
from aurelis.platform.scheduler.scheduler import Scheduler

__all__ = ["Runtime", "COMPANY_SCOPE_ID"]

COMPANY_SCOPE_ID = "AURELIS"
"""Scope id of the company-wide budget. A constant rather than a row, because
there is exactly one company and inventing a table for it would be ceremony."""


@dataclass
class Runtime:
    """Everything the platform needs, constructed once."""

    settings: Settings
    clock: Clock
    database: Database
    ledger: Ledger
    artifacts: ArtifactStore
    budget: BudgetLedger
    queue: TaskQueue
    scheduler: Scheduler
    provider: CachingProvider

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        clock: Clock | None = None,
        provider: ModelProvider | None = None,
    ) -> Runtime:
        """Wire the platform.

        Does not create the schema — that is ``aurelis db init``, an explicit
        act. A process that silently created a database on startup would make
        "which workspace am I in?" a question nobody thinks to ask until the
        wrong one has a day's work in it.
        """
        resolved = settings or load_settings()
        resolved.ensure_workspace()
        the_clock = clock or SystemClock()

        database = Database(resolved)
        ledger = Ledger(the_clock)
        artifacts = ArtifactStore(resolved.object_store, ledger, the_clock)
        budget = BudgetLedger(ledger, the_clock)
        queue = TaskQueue(ledger, budget, the_clock)
        scheduler = Scheduler(queue, ledger, the_clock)
        model_provider = build_provider(resolved, artifacts, ledger=ledger, inner=provider)

        return cls(
            settings=resolved,
            clock=the_clock,
            database=database,
            ledger=ledger,
            artifacts=artifacts,
            budget=budget,
            queue=queue,
            scheduler=scheduler,
            provider=model_provider,
        )

    def initialise(self) -> tuple[str, ...]:
        """Create the schema, install invariants, open the company budget."""
        triggers = self.database.create_all(install_triggers=self.settings.strict_integrity)
        with self.database.session() as session:
            first_run = self.ledger.count(session) == 0
            if first_run:
                self.ledger.append(
                    session,
                    kind=EventKind.DATABASE_INITIALISED,
                    actor=Actor.OPERATOR,
                    subject=COMPANY_SCOPE_ID,
                    payload={
                        "dialect": self.database.dialect,
                        "aurelis_version": __version__,
                        "strict_integrity": self.settings.strict_integrity,
                        "triggers": list(triggers),
                    },
                )
            self.budget.open(
                session,
                scope=BudgetScope.COMPANY,
                scope_id=COMPANY_SCOPE_ID,
                usd=Decimal(self.settings.company_budget_usd),
                tokens=self.settings.company_budget_tokens,
                period=BudgetPeriod.LIFETIME,
            )
        return triggers

    def close(self) -> None:
        self.database.dispose()
