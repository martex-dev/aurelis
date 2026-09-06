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
from aurelis.agents.guards import install_guards
from aurelis.agents.loop import AgentWorker
from aurelis.agents.roster import Roster
from aurelis.agents.tools import ToolBox
from aurelis.alerts.service import Alerts
from aurelis.comms.channels import Comms
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.config import Settings, load_settings
from aurelis.core.enums import Actor, BudgetPeriod, BudgetScope, EventKind
from aurelis.meetings.chair import Chair
from aurelis.meetings.forecasts import ForecastScorer
from aurelis.memory.graph import KnowledgeGraph
from aurelis.memory.lessons import Lessons
from aurelis.missions.missions import Missions
from aurelis.org.seed import registry_fingerprint, seed_org
from aurelis.orgdev.development import OrgDevelopment
from aurelis.orgdev.experiments import OrgExperiments
from aurelis.orgdev.handover import Handover
from aurelis.orgdev.invariants import install_org_invariants
from aurelis.platform.artifacts.store import ArtifactStore
from aurelis.platform.budget.ledger import BudgetLedger
from aurelis.platform.db.session import Database
from aurelis.platform.ledger.ledger import Ledger
from aurelis.platform.llm.cache import CachingProvider
from aurelis.platform.llm.factory import build_provider
from aurelis.platform.llm.providers import ModelProvider
from aurelis.platform.queue.queue import TaskQueue
from aurelis.platform.scheduler.scheduler import Scheduler
from aurelis.portfolio.construction import Book
from aurelis.research.lifecycle import Research
from aurelis.research.triggers import install_research_invariants
from aurelis.risk.authority import Risk
from aurelis.strategy.gates import Gates
from aurelis.strategy.lifecycle import Strategies
from aurelis.strategy.synthesis import Synthesis
from aurelis.strategy.triggers import install_strategy_invariants
from aurelis.trading.brokers import BrokerAdapter, adapters
from aurelis.trading.cycle import PaperCycle
from aurelis.trading.execution import Execution
from aurelis.trading.posttrade import PostTrade
from aurelis.trading.states import BrokerKind
from aurelis.trading.triggers import install_trading_invariants
from aurelis.training.onboarding import Onboarding
from aurelis.training.suite import TrainingSuite
from aurelis.training.triggers import install_training_invariants

__all__ = ["Runtime", "COMPANY_SCOPE_ID"]

COMPANY_SCOPE_ID = "AURELIS"
"""Scope id of the company-wide budget. A constant rather than a row, because
there is exactly one company and inventing a table for it would be ceremony."""


@dataclass
class Runtime:
    """Everything the company needs, constructed once."""

    settings: Settings
    clock: Clock
    database: Database
    ledger: Ledger
    artifacts: ArtifactStore
    budget: BudgetLedger
    queue: TaskQueue
    scheduler: Scheduler
    provider: CachingProvider
    roster: Roster
    tools: ToolBox
    comms: Comms
    missions: Missions
    chair: Chair
    forecasts: ForecastScorer
    research: Research
    synthesis: Synthesis
    gates: Gates
    strategies: Strategies
    book: Book
    risk: Risk
    execution: Execution
    posttrade: PostTrade
    cycle: PaperCycle
    alerts: Alerts
    brokers: dict[BrokerKind, BrokerAdapter]
    graph: KnowledgeGraph
    lessons: Lessons
    training: TrainingSuite
    onboarding: Onboarding
    handover: Handover
    orgdev: OrgDevelopment
    org_experiments: OrgExperiments
    worker: AgentWorker

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

        roster = Roster(ledger, the_clock)
        tools = ToolBox(ledger, the_clock)
        comms = Comms(artifacts, ledger, the_clock)
        missions = Missions(artifacts, budget, ledger, the_clock)
        chair = Chair(
            roster=roster,
            provider=model_provider,
            tools=tools,
            artifacts=artifacts,
            ledger=ledger,
            queue=queue,
            clock=the_clock,
        )
        forecasts = ForecastScorer(ledger, the_clock)
        research = Research(artifacts, ledger, the_clock)
        synthesis = Synthesis(ledger, the_clock)
        gates = Gates(ledger, the_clock)
        strategies = Strategies(gates, ledger, the_clock)
        book = Book(ledger, the_clock)
        risk = Risk(ledger, the_clock)
        execution = Execution(ledger, the_clock)
        posttrade = PostTrade(ledger, the_clock)
        alerts = Alerts(ledger, the_clock)
        brokers = adapters()
        cycle = PaperCycle(
            risk=risk,
            execution=execution,
            posttrade=posttrade,
            book=book,
            alerts=alerts,
            ledger=ledger,
            clock=the_clock,
        )
        graph = KnowledgeGraph(the_clock)
        lessons = Lessons(ledger, the_clock)
        # One suite, one bench, for the life of the process. Every engine run
        # it makes is a pure function of (scenario, seed, spec), so onboarding
        # a cohort of seventeen costs what onboarding one costs.
        training = TrainingSuite()
        onboarding = Onboarding(training, ledger, the_clock)
        handover = Handover(comms, ledger, the_clock)
        orgdev = OrgDevelopment(handover, ledger, the_clock)
        org_experiments = OrgExperiments(training, ledger, the_clock)
        worker = AgentWorker(
            roster=roster,
            queue=queue,
            budget=budget,
            tools=tools,
            comms=comms,
            artifacts=artifacts,
            provider=model_provider,
            ledger=ledger,
            clock=the_clock,
        )

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
            roster=roster,
            tools=tools,
            comms=comms,
            missions=missions,
            chair=chair,
            forecasts=forecasts,
            research=research,
            synthesis=synthesis,
            gates=gates,
            strategies=strategies,
            book=book,
            risk=risk,
            execution=execution,
            posttrade=posttrade,
            cycle=cycle,
            alerts=alerts,
            brokers=brokers,
            graph=graph,
            lessons=lessons,
            training=training,
            onboarding=onboarding,
            handover=handover,
            orgdev=orgdev,
            org_experiments=org_experiments,
            worker=worker,
        )

    def initialise(self) -> tuple[str, ...]:
        """Create the schema, install invariants, seed the org, open the budget.

        Order matters: the write-scope guards join against the charter tables,
        so the org must be seeded before any agent can write anything.
        """
        triggers = self.database.create_all(install_triggers=self.settings.strict_integrity)
        if self.settings.strict_integrity:
            with self.database.engine.begin() as connection:
                triggers = (
                    *triggers,
                    *install_guards(connection),
                    *install_research_invariants(connection),
                    *install_strategy_invariants(connection),
                    *install_trading_invariants(connection),
                    *install_training_invariants(connection),
                    *install_org_invariants(connection),
                )
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

            charters, desks = seed_org(session, now=self.clock.now())
            if charters or desks:
                self.ledger.append(
                    session,
                    kind=EventKind.ORG_SEEDED,
                    actor=Actor.OPERATOR,
                    subject=COMPANY_SCOPE_ID,
                    payload={
                        "charters": charters,
                        "desks": desks,
                        "fingerprint": registry_fingerprint()[:16],
                    },
                )
            self.comms.ensure_channels(session, at=self.clock.now())
        return triggers

    def staff(self) -> int:
        """Hire the launch roster and put everyone to work.

        Idempotent. Separate from :meth:`initialise` because staffing a company
        is a decision, not a side effect of creating a database.
        """
        with self.database.session() as session:
            hired = self.roster.hire_launch_roster(session, at=self.clock.now())
            for agent in hired:
                self.comms.enrol(
                    session,
                    agent.ref,
                    department=agent.department.value,
                    desk=agent.desk.value if agent.desk else None,
                    at=self.clock.now(),
                )
            self.roster.onboard_all(
                session, at=self.clock.now(), onboarding=self.onboarding
            )
        return len(hired)

    def close(self) -> None:
        self.database.dispose()
