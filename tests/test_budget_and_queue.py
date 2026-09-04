"""Budgets, refusal at dispatch, and the durable task queue."""

from __future__ import annotations

from decimal import Decimal

import pytest

from aurelis.core.enums import BudgetPeriod, BudgetScope, EventKind, TaskStatus
from aurelis.core.errors import IntegrityViolation
from aurelis.platform.budget.ledger import BudgetEnvelope, Spend
from aurelis.runtime import COMPANY_SCOPE_ID, Runtime

MISSION = "MSN-0001"
PROJECT = "PRJ-0001"


def _envelope() -> BudgetEnvelope:
    return BudgetEnvelope(company=COMPANY_SCOPE_ID, mission=MISSION, project=PROJECT)


# ------------------------------------------------------------------- budgets


def test_company_budget_is_opened_on_init(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        spent = runtime.budget.spent(session, BudgetScope.COMPANY, COMPANY_SCOPE_ID)
    assert spent.usd == 0


def test_reopening_a_budget_does_not_reset_it(runtime: Runtime) -> None:
    """A setup command re-run must not silently forgive a day's spend."""
    with runtime.database.session() as session:
        first = runtime.budget.open(
            session, scope=BudgetScope.MISSION, scope_id=MISSION, usd=Decimal("5")
        )
        again = runtime.budget.open(
            session, scope=BudgetScope.MISSION, scope_id=MISSION, usd=Decimal("999")
        )
    assert again.budget_id == first.budget_id
    assert again.limit_usd == Decimal("5")


def test_spend_is_attributed_to_every_scope(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.budget.record(
            session, _envelope(), Spend(Decimal("0.25"), 100), reason="test"
        )
    with runtime.database.session() as session:
        assert runtime.budget.spent(session, BudgetScope.COMPANY, COMPANY_SCOPE_ID).usd == Decimal(
            "0.25"
        )
        assert runtime.budget.spent(session, BudgetScope.MISSION, MISSION).usd == Decimal("0.25")
        assert runtime.budget.spent(session, BudgetScope.PROJECT, PROJECT).tokens == 100


def test_zero_cost_work_is_still_recorded(runtime: Runtime) -> None:
    """Under a subscription every call costs $0. A ledger that skipped them
    would show a company that never did anything."""
    with runtime.database.session() as session:
        runtime.budget.record(session, _envelope(), Spend(Decimal("0"), 500), reason="free")
    with runtime.database.session() as session:
        assert runtime.budget.spent(session, BudgetScope.MISSION, MISSION).tokens == 500


def test_a_limit_of_zero_means_unmetered_not_forbidden(runtime: Runtime) -> None:
    """An unmetered subscription sets money limits to zero and expects work."""
    with runtime.database.session() as session:
        runtime.budget.open(
            session, scope=BudgetScope.MISSION, scope_id=MISSION, usd=Decimal("0"), tokens=0
        )
        decision = runtime.budget.check(
            session, BudgetEnvelope(company=None, mission=MISSION), Spend(Decimal("1000"), 10**9)
        )
    assert decision.allowed


def test_refusal_names_the_innermost_binding_level(runtime: Runtime) -> None:
    """"Over budget" is unactionable; naming the level says which knob to turn."""
    with runtime.database.session() as session:
        runtime.budget.open(
            session, scope=BudgetScope.MISSION, scope_id=MISSION, usd=Decimal("5")
        )
        runtime.budget.open(
            session, scope=BudgetScope.PROJECT, scope_id=PROJECT, usd=Decimal("0.50")
        )
        decision = runtime.budget.check(session, _envelope(), Spend(Decimal("1.00"), 0))

    assert not decision.allowed
    assert decision.bound_by is BudgetScope.PROJECT
    assert decision.bound_scope_id == PROJECT
    assert "PRJ-0001" in decision.describe()


def test_tokens_and_money_bind_independently(runtime: Runtime) -> None:
    """Under a subscription tokens are scarce and dollars are not."""
    with runtime.database.session() as session:
        runtime.budget.open(
            session,
            scope=BudgetScope.MISSION,
            scope_id=MISSION,
            usd=Decimal("0"),
            tokens=1_000,
        )
        decision = runtime.budget.check(
            session, BudgetEnvelope(company=None, mission=MISSION), Spend(Decimal("0"), 5_000)
        )
    assert not decision.allowed
    assert decision.currency == "tokens"


def test_daily_budgets_open_a_fresh_window(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        first = runtime.budget.open(
            session,
            scope=BudgetScope.AGENT_DAY,
            scope_id="AG-0001",
            tokens=100,
            period=BudgetPeriod.DAILY,
        )
    runtime.clock.advance(days=1)  # type: ignore[attr-defined]
    with runtime.database.session() as session:
        tomorrow = runtime.budget.open(
            session,
            scope=BudgetScope.AGENT_DAY,
            scope_id="AG-0001",
            tokens=100,
            period=BudgetPeriod.DAILY,
        )
    assert tomorrow.budget_id != first.budget_id
    assert tomorrow.period_key != first.period_key


# --------------------------------------------------------------------- queue


def test_enqueue_allocates_a_reference_code(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        task = runtime.queue.enqueue(session, kind="research.test")
    assert task.ref.startswith("TSK-")


def test_reference_codes_are_monotonic(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        refs = [runtime.queue.enqueue(session, kind="k").ref for _ in range(3)]
    assert refs == sorted(refs)
    assert len(set(refs)) == 3


def test_claim_returns_highest_priority_first(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.queue.enqueue(session, kind="k", priority=200, payload={"which": "low"})
        runtime.queue.enqueue(session, kind="k", priority=10, payload={"which": "high"})
        claimed = runtime.queue.claim(session, worker="W")
    assert claimed is not None
    assert claimed.payload["which"] == "high"


def test_claim_on_empty_queue_returns_none(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        assert runtime.queue.claim(session, worker="W") is None


def test_a_task_addressed_to_an_agent_is_not_claimable_by_others(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.queue.enqueue(session, kind="k", assignee="AG-0001")
        assert runtime.queue.claim(session, worker="AG-0002", assignee="AG-0002") is None
        assert runtime.queue.claim(session, worker="AG-0001", assignee="AG-0001") is not None


def test_a_task_cannot_be_claimed_twice(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.queue.enqueue(session, kind="k")
        assert runtime.queue.claim(session, worker="W1") is not None
        assert runtime.queue.claim(session, worker="W2") is None


def test_succeed_requires_a_claim(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        task = runtime.queue.enqueue(session, kind="k")
        with pytest.raises(IntegrityViolation, match="not claimed"):
            runtime.queue.succeed(session, task)


def test_failure_is_terminal_by_default(runtime: Runtime) -> None:
    """Retrying a failure into success would erase the only signal it carries."""
    with runtime.database.session() as session:
        runtime.queue.enqueue(session, kind="k")
        task = runtime.queue.claim(session, worker="W")
        assert task is not None
        runtime.queue.fail(session, task, reason="schema violation")
        assert task.status == TaskStatus.FAILED
        assert runtime.queue.depth(session) == 0


def test_infrastructure_failure_requeues(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.queue.enqueue(session, kind="k")
        task = runtime.queue.claim(session, worker="W")
        assert task is not None
        runtime.queue.fail(session, task, reason="timeout", retryable=True)
        assert task.status == TaskStatus.QUEUED
        assert runtime.queue.depth(session) == 1


def test_unaffordable_task_is_refused_at_dispatch_not_raised(runtime: Runtime) -> None:
    """Budget exhaustion is a research outcome, not a crash."""
    with runtime.database.session() as session:
        runtime.budget.open(
            session, scope=BudgetScope.PROJECT, scope_id=PROJECT, usd=Decimal("0.01")
        )
        task = runtime.queue.enqueue(
            session,
            kind="expensive",
            allowance=Spend(Decimal("5.00"), 0),
            envelope=_envelope(),
        )

    assert task.status == TaskStatus.REFUSED_BUDGET
    assert task.budget_scope == BudgetScope.PROJECT.value
    assert "PRJ-0001" in (task.failure_reason or "")


def test_refusal_is_recorded_as_an_event(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.budget.open(
            session, scope=BudgetScope.PROJECT, scope_id=PROJECT, usd=Decimal("0.01")
        )
        task = runtime.queue.enqueue(
            session, kind="expensive", allowance=Spend(Decimal("5"), 0), envelope=_envelope()
        )
        events = runtime.ledger.for_subject(session, task.ref)

    assert [e.kind for e in events] == [EventKind.TASK_REFUSED_BUDGET.value]


def test_a_refused_task_never_enters_the_queue(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.budget.open(
            session, scope=BudgetScope.PROJECT, scope_id=PROJECT, usd=Decimal("0.01")
        )
        runtime.queue.enqueue(
            session, kind="expensive", allowance=Spend(Decimal("5"), 0), envelope=_envelope()
        )
        assert runtime.queue.depth(session) == 0


def test_lifecycle_emits_the_expected_events(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        task = runtime.queue.enqueue(session, kind="k")
        claimed = runtime.queue.claim(session, worker="W")
        assert claimed is not None
        runtime.queue.succeed(session, claimed)
        kinds = [e.kind for e in runtime.ledger.for_subject(session, task.ref)]

    assert kinds == [
        EventKind.TASK_ENQUEUED.value,
        EventKind.TASK_CLAIMED.value,
        EventKind.TASK_SUCCEEDED.value,
    ]


def test_a_rolled_back_transaction_burns_no_reference_number(runtime: Runtime) -> None:
    """A gap in HYP- would look like a hypothesis somebody deleted."""
    try:
        with runtime.database.session() as session:
            runtime.queue.enqueue(session, kind="k")
            raise RuntimeError("abandon")
    except RuntimeError:
        pass

    with runtime.database.session() as session:
        task = runtime.queue.enqueue(session, kind="k")
    assert task.ref == "TSK-0001"
