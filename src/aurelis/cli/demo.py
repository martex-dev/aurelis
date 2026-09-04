"""``aurelis demo`` — M0's acceptance test, runnable by hand.

A scripted exchange between two placeholder actors, end to end through the
whole platform, at zero cost. It is not the company: there are no agents, no
departments and no meetings yet. It exists to prove that the machinery those
will need actually works —

* a budget is opened and checked at dispatch,
* tasks are queued, claimed and completed,
* model calls go through the provider, get recorded, and hit the cache the
  second time,
* every output is stored as a content-addressed artifact,
* every step appends to the hash chain,
* and the chain verifies afterwards.

The second exchange is deliberately identical to the first. It must cost
nothing and be served from cache — which is the single most important cost
property of the whole system, and worth an assertion rather than a hope.

Everything here is torn out at M1, when real agents replace the placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa

from aurelis.core.enums import BudgetPeriod, BudgetScope, EventKind, TaskStatus
from aurelis.platform.budget.ledger import BudgetEnvelope, Spend
from aurelis.platform.db.tables import Artifact
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef
from aurelis.runtime import COMPANY_SCOPE_ID, Runtime

__all__ = ["DemoResult", "run_demo"]

_MISSION = "MSN-DEMO"

_PARTICIPANTS = (
    (
        "analyst",
        "You are an analyst reporting one observation. Be brief and specific.",
        "Summarise the state of the platform you are running on.",
    ),
    (
        "critic",
        "You are a critic. Name the weakest part of what you are given.",
        "What is the weakest claim an empty research record can support?",
    ),
)


@dataclass(frozen=True)
class DemoResult:
    """What the demo did, for the CLI to render and tests to assert on."""

    tasks: int
    model_calls: int
    cache_hits: int
    artifacts: int
    events: int
    usd: Decimal
    tokens: int
    chain_ok: bool
    chain_detail: str
    transcript: list[tuple[str, str]]

    @property
    def free(self) -> bool:
        return self.usd == 0


def run_demo(runtime: Runtime, *, rounds: int = 2) -> DemoResult:
    """Run the scripted exchange. Idempotent enough to run repeatedly."""
    model = ModelRef(provider=runtime.provider.name, model="mock-1", max_tokens=512)
    envelope = BudgetEnvelope(company=COMPANY_SCOPE_ID, mission=_MISSION)
    transcript: list[tuple[str, str]] = []

    with runtime.database.session() as session:
        # A mission-scoped allowance. Deliberately generous: the point is to
        # exercise the check, not to hit it.
        runtime.budget.open(
            session,
            scope=BudgetScope.MISSION,
            scope_id=_MISSION,
            usd=Decimal("1.00"),
            tokens=100_000,
            period=BudgetPeriod.LIFETIME,
        )

    for round_index in range(rounds):
        for actor, system_prompt, question in _PARTICIPANTS:
            with runtime.database.session() as session:
                task = runtime.queue.enqueue(
                    session,
                    kind="demo.turn",
                    assignee=actor,
                    subject=_MISSION,
                    payload={"round": round_index + 1, "question": question},
                    allowance=Spend(Decimal("0.05"), 5_000),
                    envelope=envelope,
                )
                if task.status != TaskStatus.QUEUED:
                    # A refusal is a legitimate outcome and is already recorded;
                    # the demo stops rather than pretending it did the work.
                    break

                claimed = runtime.queue.claim(session, worker=actor, assignee=actor)
                assert claimed is not None, "a task was queued but could not be claimed"

                response = runtime.provider.complete(
                    session,
                    LlmRequest(
                        model=model,
                        system=system_prompt,
                        messages=(Message("user", question),),
                        actor=actor,
                        task_ref=claimed.ref,
                    ),
                )

                stored = runtime.artifacts.put_json(
                    session,
                    {
                        "actor": actor,
                        "round": round_index + 1,
                        "question": question,
                        "answer": response.text,
                    },
                    kind="demo_turn",
                    produced_by=claimed.ref,
                    actor=actor,
                )

                runtime.budget.record(
                    session,
                    envelope,
                    Spend(response.usd, response.usage.total),
                    actor=actor,
                    reason="demo.turn",
                    task_ref=claimed.ref,
                )

                runtime.queue.succeed(session, claimed, result_digest=stored.digest)
                runtime.ledger.append(
                    session,
                    kind=EventKind.DEMO_EXCHANGE,
                    actor=actor,
                    subject=_MISSION,
                    payload={
                        "round": round_index + 1,
                        "task": claimed.ref,
                        "artifact": stored.digest[:12],
                        "cache_hit": response.cache_hit,
                    },
                )

                if round_index == 0:
                    transcript.append((actor, response.text))

    with runtime.database.session() as session:
        verification = runtime.ledger.verify(session)
        stats = runtime.provider.stats(session)
        spent = runtime.budget.spent(session, BudgetScope.MISSION, _MISSION)
        counts = runtime.queue.counts_by_status(session)
        artifacts = session.execute(
            sa.select(sa.func.count()).select_from(Artifact)
        ).scalar_one()
        events = runtime.ledger.count(session)

    return DemoResult(
        tasks=counts.get("succeeded", 0),
        model_calls=stats.calls,
        cache_hits=stats.hits,
        artifacts=int(artifacts),
        events=events,
        usd=spent.usd,
        tokens=spent.tokens,
        chain_ok=verification.ok,
        chain_detail=verification.describe(),
        transcript=transcript,
    )
