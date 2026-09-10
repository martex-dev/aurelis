"""M22 — the paper cycle gets a driver, and the gates get read from the record.

M20's mandate reported ``risk_cleared`` and ``paper_gap_measured`` as unmet
with a note that the machinery existed and no command drove it. Building the
command turned the question inside out: the missing piece was never a switch,
it was **a reader**. A version reaches a paper book only through the promotion
gates, so what an operator actually needed was seven observables and an honest
answer about which of them the company can supply.

Five acceptance criteria, each with a test named after it:

* the gates are read from the record, and a silence is not a zero,
* a deployment refuses when a gate has no observable,
* the rule that trades is the rule that was measured,
* the walk trades bars the research window never read,
* the gap is derived from the book's own fills.

**Nothing here touches the network.** The snapshot is ingested from a recorded
payload, exactly as M21's tests do.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.authoring.attempt import caveat_for, data_caveat, run_authoring
from aurelis.authoring.design import Design, baseline_spec, render
from aurelis.authoring.standin import scripted_author
from aurelis.authoring.tables import AuthoringAttempt
from aurelis.core.errors import IntegrityViolation
from aurelis.intel.live import CoinbaseCandles
from aurelis.intel.snapshots import MarketSnapshot, SnapshotSource
from aurelis.meetings.tables import MeetingObjection
from aurelis.org.desks import Desk
from aurelis.platform.llm.providers import MockProvider
from aurelis.portfolio.tables import Allocation
from aurelis.research.tables import Replication, Result
from aurelis.runtime import Runtime
from aurelis.strategy.gates import COMPARISONS, default_criteria
from aurelis.strategy.states import Gate, PortfolioMode, StrategyState
from aurelis.trading.deployment import RESEARCH_WALK, deploy, open_paper_book
from aurelis.trading.execution import approved_quantity
from aurelis.trading.paper import (
    HOLD_OUT,
    deployments,
    design_of,
    held_out,
    intents_at,
    measure,
    realised,
    sleeve_curve,
    walk,
)
from aurelis.trading.readiness import PARTICIPATION, gather, unmet
from aurelis.trading.states import OrderSide
from aurelis.trading.tables import Fill, Order

_HOUR = 3600
_START = 1_780_000_000
_BARS = 400


def _rows(count: int) -> list[list[float]]:
    """Vendor-shaped candles: [time, low, high, open, close, volume].

    A gentle trend with a wobble, so a momentum rule has something to react to
    and the book does not sit flat for four hundred bars.
    """
    out: list[list[float]] = []
    for index in reversed(range(count)):
        drift = Decimal(index) / Decimal(10)
        wobble = Decimal((index % 17) - 8) / Decimal(4)
        close = Decimal(100) + drift + wobble
        out.append(
            [
                _START + index * _HOUR,
                float(close - 1),
                float(close + 1),
                float(close - Decimal("0.25")),
                float(close),
                50_000.0 + (index % 5),
            ]
        )
    return out


class _Recorded:
    """A recorded response. The tests' entire contact with a vendor."""

    def __init__(self, rows: list[list[float]]) -> None:
        self._rows = rows

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(json.dumps(self._rows).encode())


@pytest.fixture
def company(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=scripted_author)
    )
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _snapshot(company: Runtime, session: sa.orm.Session) -> MarketSnapshot:
    return company.snapshots.ingest(
        session,
        CoinbaseCandles(opener=_Recorded(_rows(_BARS))),
        desk="crypto",
        symbol="BTC-USD",
        interval="1h",
        bars=_BARS,
    )


def _authored(company: Runtime) -> tuple[str, MarketSnapshot]:
    """One authored version, measured on the snapshot's early window."""
    with company.database.session() as session:
        snapshot = _snapshot(company, session)
        source = SnapshotSource(session, snapshot, upto=held_out(snapshot.bars))
    outcome = run_authoring(
        company, desk=Desk.CRYPTO, agent_handle="STRAT", source=source
    )
    return outcome.authored.version_ref, snapshot


def _refs(company: Runtime, session: sa.orm.Session) -> dict[str, str]:
    handles = {
        "validator": "VALID",
        "governor": "GOV",
        "risk": "RISK",
        "portfolio": "PM",
        "trader": "TRADE",
    }
    return {
        role: company.roster.by_handle(session, name).ref
        for role, name in handles.items()
    }


def _cycle_actors(refs: dict[str, str]) -> dict[str, str]:
    return {
        "proposer": refs["portfolio"],
        "assessor": refs["risk"],
        "approver": refs["trader"],
        "executor": refs["trader"],
        "analyst": refs["trader"],
    }


def _force_deployed(
    company: Runtime, session: sa.orm.Session, version_ref: str
) -> tuple[str, dict[str, str]]:
    """A version in a paper book, with the gates satisfied *by the test*.

    Deliberately not through :func:`deploy`. The authored designs in this
    repository do not clear their own gates — that is the standing result, and
    a helper that made them clear it would be faking the finding. What these
    tests need is the *state* a cleared version arrives in, so the walk and the
    gap can be exercised at all, and the values below are the test's, stated
    plainly as such.
    """
    refs = _refs(company, session)
    version = company.strategies.version(session, version_ref)
    for target, reason in RESEARCH_WALK:
        company.strategies.transition(
            session,
            strategy_ref=version.strategy_ref,
            target=target,
            reason=reason,
            actor=refs["validator"],
        )
    passing: dict[Gate, Decimal] = {
        Gate.A_STATISTICAL: Decimal("0.97"),
        Gate.B_BENCHMARK: Decimal("0.31"),
        Gate.C_INDEPENDENCE: Decimal("0"),
        Gate.D_INTEGRITY: Decimal("0"),
        Gate.E_REPLICATION: Decimal("1"),
        Gate.F_CUSTODY: Decimal("1"),
        Gate.G_CAPACITY: Decimal("4"),
    }
    for gate, criterion in default_criteria("crypto").items():
        company.gates.register(
            session,
            version_ref=version_ref,
            gate=gate,
            metric=str(criterion["metric"]),
            comparison=str(criterion["comparison"]),
            value=Decimal(str(criterion["value"])),
            registered_by=refs["validator"],
        )
        company.gates.evaluate(
            session,
            version_ref=version_ref,
            gate=gate,
            observed=passing[gate],
            evaluated_by=refs["validator"],
        )
    company.strategies.promote(
        session,
        version_ref=version_ref,
        decided_by_meeting="MTG-0002",
        actor=refs["governor"],
    )
    company.strategies.transition(
        session,
        strategy_ref=version.strategy_ref,
        target=StrategyState.PAPER_TRADING,
        reason="gates cleared",
        actor=refs["risk"],
    )
    book = open_paper_book(
        company,
        session,
        desk="crypto",
        equity=Decimal("100000"),
        opened_by=refs["portfolio"],
    )
    company.book.allocate(
        session,
        portfolio_ref=book,
        version_ref=version_ref,
        weight=Decimal("0.25"),
        rationale="deployed for a forward paper walk",
        decided_by=refs["portfolio"],
    )
    return book, refs


# ------------------- acceptance (a): the gates are read, silence is not zero


def test_the_gates_are_read_from_the_record_and_silence_is_not_zero(
    company: Runtime,
) -> None:
    """M22 acceptance (a).

    Seven gates, seven observables, each fetched from something the company
    already wrote down. Two of them come back silent on a fresh version, and
    that is the load-bearing distinction: "nobody measured this" and "this
    measured zero" differ in exactly the direction that promotes strategies.
    """
    version_ref, _snap = _authored(company)
    with company.database.session() as session:
        readiness = gather(
            session, version_ref=version_ref, intended=Decimal("25000")
        )

    assert len(readiness.evidence) == len(Gate)
    assert {item.gate for item in readiness.evidence} == set(Gate)
    assert not readiness.complete, "a fresh version cannot answer every gate"

    silent = {item.gate for item in readiness.silent}
    assert Gate.D_INTEGRITY in silent, "nobody has objected to it"
    assert Gate.F_CUSTODY in silent, "no sealed query was ever released"
    for item in readiness.silent:
        assert item.value is None
        assert len(item.source) > 40, "a silence says what is absent"

    # And the answerable ones cite where they came from precisely enough to
    # go and look: a run, an attempt, a snapshot.
    for item in readiness.answerable:
        assert item.value is not None
        assert any(
            token in item.source
            for token in ("AUT-", "RUN-", "SNP-", "PTF-", "REG-", "no ")
        ), item.source


def test_a_replication_that_held_moves_the_gate_it_answers(company: Runtime) -> None:
    """The evidence is live, not a snapshot of the moment it was written.

    Gate E counts replications that held. M21 gave the company a writer for
    that table; this is the gate reading it.
    """
    version_ref, _snap = _authored(company)
    with company.database.session() as session:
        attempt = session.execute(
            sa.select(AuthoringAttempt).where(
                AuthoringAttempt.version_ref == version_ref
            )
        ).scalar_one()
        before = gather(session, version_ref=version_ref).evidence[4]
        assert before.value == Decimal(0)

        session.add(
            Replication(
                replication_id=__import__("uuid").uuid4(),
                ref="RPL-9001",
                parent_registration_ref=attempt.registration_ref,
                run_ref=attempt.run_ref,
                varied="seed",
                outcome="held",
                detail="held under a declared variation",
                author=company.roster.by_handle(session, "VALID").ref,
                created_at=company.clock.now(),
            )
        )
        session.flush()
        after = gather(session, version_ref=version_ref).evidence[4]

    assert after.value == Decimal(1)
    assert after.gate is Gate.E_REPLICATION


def test_capacity_is_computed_from_recorded_volume_or_not_at_all(
    company: Runtime,
) -> None:
    """Gate G divides a market's own traded value by the size intended for it.

    Silent without a snapshot, because a capacity claim resting on invented
    volume reads as diligence and contains nothing.
    """
    version_ref, snapshot = _authored(company)
    with company.database.session() as session:
        item = gather(
            session, version_ref=version_ref, intended=Decimal("25000")
        ).evidence[6]
        zero_size = gather(session, version_ref=version_ref).evidence[6]

    assert item.gate is Gate.G_CAPACITY
    assert item.value is not None and item.value > 0
    assert snapshot.ref in item.source
    assert str(PARTICIPATION) in item.source, "the assumption travels with it"
    assert zero_size.value is None, "capacity over zero size is not a fact"


# ---------------- acceptance (b): a deployment refuses on a silent gate


def test_a_deployment_refuses_when_a_gate_has_no_observable(
    company: Runtime,
) -> None:
    """M22 acceptance (b).

    The authored design cannot clear its own gates, and two of them cannot
    even be asked. Both refusals are reported; neither is worked around.
    """
    version_ref, _snap = _authored(company)
    with company.database.session() as session:
        refs = _refs(company, session)
        book = open_paper_book(
            company,
            session,
            desk="crypto",
            equity=Decimal("100000"),
            opened_by=refs["portfolio"],
        )
        outcome = deploy(
            company,
            session,
            version_ref=version_ref,
            portfolio_ref=book,
            weight=Decimal("0.25"),
            actors=refs,
        )
        allocations = list(
            session.execute(
                sa.select(Allocation).where(Allocation.portfolio_ref == book)
            ).scalars()
        )

    assert not outcome.deployed
    assert outcome.refusal, "a refusal says why"
    assert not allocations, "nothing reached the book"
    assert outcome.failures, "the gates that could be asked, and failed"


def test_the_gates_are_registered_before_they_are_evaluated(
    company: Runtime,
) -> None:
    """A criterion chosen after its observation is a description of what
    happened. The trigger behind the table refuses that ordering; this is the
    deployment path obeying it rather than relying on it."""
    version_ref, _snap = _authored(company)
    with company.database.session() as session:
        for gate, criterion in default_criteria("crypto").items():
            company.gates.register(
                session,
                version_ref=version_ref,
                gate=gate,
                metric=str(criterion["metric"]),
                comparison=str(criterion["comparison"]),
                value=Decimal(str(criterion["value"])),
                registered_by=company.roster.by_handle(session, "VALID").ref,
            )
        report = company.gates.report(session, version_ref)

    assert len(report.unevaluated) == len(Gate)
    assert not report.clear, "registering a bar is not clearing it"


def test_unmet_reads_the_same_criteria_the_registration_uses(
    company: Runtime,
) -> None:
    """One definition of "did it pass", so a preview and a decision agree."""
    version_ref, _snap = _authored(company)
    with company.database.session() as session:
        readiness = gather(
            session, version_ref=version_ref, intended=Decimal("25000")
        )
        failures = unmet(readiness, "crypto")
        criteria = default_criteria("crypto")
        by_hand = [
            item.gate.value
            for item in readiness.answerable
            if item.value is not None
            and not COMPARISONS[str(criteria[item.gate]["comparison"])](
                item.value, Decimal(str(criteria[item.gate]["value"]))
            )
        ]

    assert [failure.split(":")[0] for failure in failures] == by_hand


def _record_answers_every_gate(
    company: Runtime, session: sa.orm.Session, version_ref: str
) -> None:
    """Fill in the evidence a version would need to clear its own gates.

    **These numbers are the test's.** No authored design in this repository
    produces a Sharpe of 2.5, and the standing result is that they do not clear
    their gates. What is being tested here is the deployment path itself — that
    a record which *can* answer every gate reaches the book, so the refusals
    everywhere else are refusals rather than a path that never worked.
    """
    import uuid

    attempt = session.execute(
        sa.select(AuthoringAttempt).where(AuthoringAttempt.version_ref == version_ref)
    ).scalar_one()
    attempt.verdict = "confirmed"
    attempt.metrics = {**attempt.metrics, "sharpe": "2.5"}
    attempt.baselines = {
        **attempt.baselines,
        "always_long": {"sharpe": "0.1", "total_return": "0.05"},
    }
    session.add(
        Replication(
            replication_id=uuid.uuid4(),
            ref="RPL-9100",
            parent_registration_ref=attempt.registration_ref,
            run_ref=attempt.run_ref,
            varied="seed",
            outcome="held",
            detail="held under a declared variation",
            author=company.roster.by_handle(session, "VALID").ref,
            created_at=company.clock.now(),
        )
    )
    session.add(
        MeetingObjection(
            objection_id=uuid.uuid4(),
            ref="OBJ-9100",
            meeting_ref="MTG-0001",
            author=company.roster.by_handle(session, "CRITIC").ref,
            target=version_ref,
            type="methodology",
            severity="major",
            statement="the window may not cover a funding regime change",
            discriminating_test={"metric": "sharpe", "split": "regime"},
            status="rejected",
            created_at=company.clock.now(),
        )
    )
    session.add(
        Result(
            result_id=uuid.uuid4(),
            run_ref=attempt.run_ref,
            metric="sharpe",
            value=Decimal("2.4"),
            unit="per_bar",
            method="custodian.sealed_release",
            split="sealed",
            computed_by="custodian",
            artifact_digest="0" * 64,
            created_at=company.clock.now(),
        )
    )
    session.flush()


def test_a_record_that_answers_every_gate_reaches_the_book(
    company: Runtime,
) -> None:
    """The positive path, so the refusals elsewhere mean something.

    Every gate answered from the record and every one passing puts the version
    in the book with a Risk limit at the sleeve — and a second deployment does
    not re-register a criterion, because re-registering after a disappointing
    measurement is how a threshold becomes a description.
    """
    version_ref, _snap = _authored(company)
    with company.database.session() as session:
        _record_answers_every_gate(company, session, version_ref)
        refs = _refs(company, session)
        book = open_paper_book(
            company,
            session,
            desk="crypto",
            equity=Decimal("100000"),
            opened_by=refs["portfolio"],
        )
        outcome = deploy(
            company,
            session,
            version_ref=version_ref,
            portfolio_ref=book,
            weight=Decimal("0.25"),
            actors=refs,
        )
        allocations = list(
            session.execute(
                sa.select(Allocation).where(
                    Allocation.portfolio_ref == book,
                    Allocation.version_ref == version_ref,
                )
            ).scalars()
        )
        limits = company.risk.live_limits(
            session, scopes={"version": version_ref}, metric="exposure"
        )
        again = deploy(
            company,
            session,
            version_ref=version_ref,
            portfolio_ref=book,
            weight=Decimal("0.25"),
            actors=refs,
        )

    assert outcome.deployed, outcome.refusal
    assert not outcome.failures, "every answerable gate passed"
    assert len(outcome.registered) == len(Gate)
    assert len(outcome.evaluated) == len(Gate)
    assert len(allocations) == 1
    assert limits and limits[0].bound == Decimal("25000.00")
    assert again.already, "a second deployment reports the book, not a decision"
    assert not again.registered, "a criterion is never re-registered"
    assert "nothing was changed" in again.describe()


# --------------- acceptance (c): the rule that trades is the rule measured


def test_the_rule_that_trades_is_the_rule_that_was_measured(
    company: Runtime,
) -> None:
    """M22 acceptance (c).

    The design is rebuilt from the attempt and checked against the digest the
    attempt recorded. A reconstruction that silently differed would produce a
    gap about a strategy the company never tested.
    """
    version_ref, _snap = _authored(company)
    with company.database.session() as session:
        design, attempt = design_of(session, version_ref)
        assert design.digest() == attempt.design_digest

        # And a design that does not match is refused rather than traded.
        attempt.design = {**attempt.design, "lookback": "six_hours"}
        session.flush()
        with pytest.raises(IntegrityViolation, match="not the rule that was measured"):
            design_of(session, version_ref)


def test_a_supplied_engine_must_be_the_engine_that_was_locked(
    company: Runtime,
) -> None:
    """Which engine ran a registration is part of what was registered."""

    class _Wrong:
        name = "martex"

        def run(self, spec: object) -> object:  # pragma: no cover - never reached
            raise AssertionError("should not run")

    version_ref, snapshot = _authored(company)
    with company.database.session() as session:
        experiment = session.execute(
            sa.text("SELECT ref FROM experiments ORDER BY ref DESC LIMIT 1")
        ).scalar_one()
        with pytest.raises(IntegrityViolation, match="part of what was registered"):
            company.research.execute(
                session, experiment_ref=str(experiment), engine=_Wrong()
            )
    assert version_ref and snapshot.ref


def test_a_baseline_reads_the_same_bars_as_the_design_it_references(
    company: Runtime,
) -> None:
    """A reference measured on the fixture while the design ran on a market
    would be answering a different question in the same units."""
    design = Design((("family", "momentum"), ("lookback", "one_day"),
                     ("threshold", "any_move"), ("direction", "long_only")))
    spec = render(
        design, desk=Desk.CRYPTO, bars=200, source="coinbase:SNP-0001[:200]"
    )
    reference = baseline_spec("always_long", desk=Desk.CRYPTO, bars=200, like=spec)

    assert spec.data.source == "coinbase:SNP-0001[:200]"
    assert reference.data.source == spec.data.source
    assert reference.backtest.costs == spec.backtest.costs


def test_the_caveat_names_the_data_it_was_measured_on() -> None:
    """M18 found this report saying a stand-in had answered while a real model
    was answering. M22 found it saying the data was a fixture while the run had
    read three thousand hours of a real market. Both halves are conditional."""
    fixture = caveat_for("mock")
    assert "fixture" in fixture

    live = caveat_for("mock", "coinbase:SNP-0001[:2100]")
    assert "fixture" not in live
    assert "coinbase:SNP-0001" in live
    assert "stopped at the moment it was fetched" in live
    assert data_caveat("fixture:crypto") == data_caveat("")


# ------------- acceptance (d): the walk trades bars research never read


def test_the_walk_trades_bars_the_research_window_never_read(
    company: Runtime,
) -> None:
    """M22 acceptance (d).

    A replay of the window the backtest ran on is not a forward test; it is
    the backtest again, paying different fees. The research source is cut at
    ``upto`` and the walk starts where it stopped.
    """
    version_ref, snapshot = _authored(company)
    research = held_out(snapshot.bars)
    with company.database.session() as session:
        book, refs = _force_deployed(company, session, version_ref)
        walked = walk(
            company,
            session,
            portfolio_ref=book,
            snapshot=snapshot,
            actors=_cycle_actors(refs),
        )
        first_order = session.execute(
            sa.select(Order.submitted_at).order_by(Order.submitted_at).limit(1)
        ).scalar()
        boundary = SnapshotSource(session, snapshot).bars(snapshot.symbol, limit=0)[
            research
        ]

    assert walked.first_bar == research
    assert walked.bars == snapshot.bars - research
    assert 0 < walked.bars < snapshot.bars
    if first_order is not None:
        # SQLite hands datetimes back naive. Compare on the same footing
        # rather than on whichever side happens to carry the offset.
        assert first_order.replace(tzinfo=None) >= boundary.timestamp.replace(
            tzinfo=None
        ), "no order predates the held-out boundary"


def test_the_hold_out_must_leave_both_halves_non_empty() -> None:
    """A snapshot too short to divide cannot support a forward test, and
    saying so beats producing one bar of one."""
    assert held_out(100) == 70
    assert held_out(100, HOLD_OUT) == 70
    with pytest.raises(IntegrityViolation, match="cannot be split"):
        held_out(1)
    with pytest.raises(IntegrityViolation, match="would be empty"):
        held_out(2, Decimal("1"))


def test_a_walk_over_a_fully_consumed_snapshot_is_refused(
    company: Runtime,
) -> None:
    """The guard that makes acceptance (d) more than a convention."""
    with company.database.session() as session:
        snapshot = _snapshot(company, session)
        source = SnapshotSource(session, snapshot)
    outcome = run_authoring(
        company, desk=Desk.CRYPTO, agent_handle="STRAT", source=source
    )
    with company.database.session() as session:
        book, refs = _force_deployed(company, session, outcome.authored.version_ref)
        with pytest.raises(IntegrityViolation, match="nothing left to trade forward"):
            walk(
                company,
                session,
                portfolio_ref=book,
                snapshot=snapshot,
                actors=_cycle_actors(refs),
            )


def test_an_intent_is_the_difference_not_the_target(company: Runtime) -> None:
    """An intent stated as the whole target would re-buy a position the book
    already holds, on every bar, forever."""
    version_ref, snapshot = _authored(company)
    with company.database.session() as session:
        book, _refs_ = _force_deployed(company, session, version_ref)
        deployed = deployments(session, portfolio_ref=book, snapshot=snapshot)
        bars = list(SnapshotSource(session, snapshot).bars(snapshot.symbol, limit=0))
        wanted = [
            intents_at(
                session, deployed, portfolio_ref=book, bars=bars, index=index
            )
            for index in range(deployed[0].research_bars, len(bars))
        ]

    fired = [intent for group in wanted for intent in group]
    assert fired, "the rule asked for something at least once"
    for intent in fired:
        assert intent.exposure == abs(intent.target - intent.held).quantize(
            Decimal("0.01")
        )
        assert intent.side in (OrderSide.BUY, OrderSide.SELL)


def test_an_intent_fires_when_the_rule_changes_its_mind_not_when_the_mark_moves(
    company: Runtime,
) -> None:
    """The first version compared the target notional against the position's
    market value, which drifts with the price on every bar — so a rule holding
    one position for a week produced seven trades, and the walk turned over
    twelve times more than the backtest it was being compared against. The
    engine holds a target *weight* and charges only when the weight changes.
    """
    version_ref, snapshot = _authored(company)
    with company.database.session() as session:
        book, refs = _force_deployed(company, session, version_ref)
        walked = walk(
            company,
            session,
            portfolio_ref=book,
            snapshot=snapshot,
            actors=_cycle_actors(refs),
        )
        deployed = deployments(session, portfolio_ref=book, snapshot=snapshot)
        path = deployed[0].path
        changes = sum(
            1
            for index in range(walked.first_bar, walked.first_bar + walked.bars)
            if index - 1 < len(path) and path[index - 1] != path[index - 2]
        )
        fills = session.execute(
            sa.select(sa.func.count())
            .select_from(Fill)
            .join(Order, Fill.order_ref == Order.ref)
            .where(Order.portfolio_ref == book)
        ).scalar_one()

    # One fill per change of mind, plus at most an entry and an exit. A driver
    # rebalancing to constant notional would produce one per bar instead.
    assert fills <= changes + 2, (
        f"{fills} fill(s) against {changes} change(s) of mind over "
        f"{walked.bars} bars"
    )
    assert walked.bars > changes + 2, "the rule did not want to trade every bar"


def test_the_first_bar_of_a_walk_has_no_prior_signal(company: Runtime) -> None:
    """A rule evaluated on the bar it trades has read the future."""
    version_ref, snapshot = _authored(company)
    with company.database.session() as session:
        book, _refs_ = _force_deployed(company, session, version_ref)
        deployed = deployments(session, portfolio_ref=book, snapshot=snapshot)
        bars = list(SnapshotSource(session, snapshot).bars(snapshot.symbol, limit=0))
        with pytest.raises(IntegrityViolation, match="read the future"):
            intents_at(session, deployed, portfolio_ref=book, bars=bars, index=0)


def test_an_approval_is_a_ceiling_so_the_size_rounds_down() -> None:
    """The cycle sized orders with quantize's default half-even rule, which
    rounds up about half the time — and a notional a hundred-millionth over
    the approval is refused outright by the database."""
    quantity = approved_quantity(Decimal("250"), Decimal("3"))
    assert quantity * Decimal("3") <= Decimal("250")
    assert quantity == Decimal("83.33333333")
    with pytest.raises(IntegrityViolation, match="zero price"):
        approved_quantity(Decimal("250"), Decimal("0"))


# --------------- acceptance (e): the gap comes from the book's own fills


def test_the_gap_is_derived_from_the_books_own_fills(company: Runtime) -> None:
    """M22 acceptance (e).

    The curve is rebuilt from the fills rather than accumulated as the walk
    goes, so the number the gap is measured from is a consequence of what the
    record says happened. A bug in the driver cannot flatter it.
    """
    version_ref, snapshot = _authored(company)
    with company.database.session() as session:
        book, refs = _force_deployed(company, session, version_ref)
        walked = walk(
            company,
            session,
            portfolio_ref=book,
            snapshot=snapshot,
            actors=_cycle_actors(refs),
        )
        gaps = measure(
            company,
            session,
            portfolio_ref=book,
            snapshot=snapshot,
            walked=walked,
        )
        fills = list(
            session.execute(
                sa.select(Fill.quantity, Fill.price, Fill.fee)
                .join(Order, Fill.order_ref == Order.ref)
                .where(Order.portfolio_ref == book)
            ).all()
        )
        assessments = session.execute(
            sa.text("SELECT count(*) FROM risk_assessments")
        ).scalar_one()

    assert walked.turns > 0, "the rule traded at least once"
    assert fills, "the paper broker filled at least one order"
    assert gaps, "a gap was measured"
    assert assessments > 0, "every intent went through Risk"

    for gap in gaps:
        assert gap.expected_source, "the expectation cites an artifact"
        assert len(gap.expected_source) == 64
        assert gap.observations > 1


def test_a_gap_is_only_measured_against_a_metric_the_backtest_produced(
    company: Runtime,
) -> None:
    """A gap against an expectation nobody stated is a comparison with
    nothing, so a metric the run never measured is skipped rather than
    defaulted."""
    version_ref, snapshot = _authored(company)
    with company.database.session() as session:
        book, refs = _force_deployed(company, session, version_ref)
        walked = walk(
            company,
            session,
            portfolio_ref=book,
            snapshot=snapshot,
            actors=_cycle_actors(refs),
        )
        gaps = measure(
            company, session, portfolio_ref=book, snapshot=snapshot, walked=walked
        )
        attempt = session.execute(
            sa.select(AuthoringAttempt).where(
                AuthoringAttempt.version_ref == version_ref
            )
        ).scalar_one()
        measured = {
            row
            for row in session.execute(
                sa.text("SELECT metric FROM results WHERE run_ref = :r"),
                {"r": attempt.run_ref},
            ).scalars()
        }

    assert {gap.metric for gap in gaps} <= measured


def test_the_curve_starts_at_the_sleeve_and_moves_only_on_fills(
    company: Runtime,
) -> None:
    """Mark-to-market equity, derived. A sleeve that never traded is flat at
    the notional it was given."""
    version_ref, snapshot = _authored(company)
    with company.database.session() as session:
        book, _refs_ = _force_deployed(company, session, version_ref)
        bars = list(SnapshotSource(session, snapshot).bars(snapshot.symbol, limit=0))
        curve = sleeve_curve(
            session,
            portfolio_ref=book,
            version_ref=version_ref,
            bars=bars,
            first_bar=held_out(snapshot.bars),
            sleeve=Decimal("25000"),
        )

    assert len(curve) == snapshot.bars - held_out(snapshot.bars)
    assert all(value == Decimal("25000") for value in curve), (
        "nothing has traded, so nothing has moved"
    )


def test_realised_metrics_come_from_the_engines_own_measurements() -> None:
    """Two implementations of "Sharpe" would put the difference between them
    into every gap and label it a finding about the market."""
    curve = [Decimal("100"), Decimal("102"), Decimal("101"), Decimal("104")]
    produced = realised(curve, trades=3, costs=Decimal("2"))

    assert produced["total_return"] == Decimal("0.04000000")
    assert produced["max_drawdown"] > 0
    assert produced["n_trades"] == Decimal(3)
    assert produced["cost_drag"] == Decimal("0.02000000")
    with pytest.raises(IntegrityViolation, match="two marks"):
        realised([Decimal("100")], trades=0, costs=Decimal(0))


# ----------------------------------------------------------------- guards


def test_a_book_traded_on_data_the_claim_was_not_made_on_is_refused(
    company: Runtime,
) -> None:
    """A gap between a claim made on one dataset and a book traded on another
    measures the distance between the datasets."""
    with company.database.session() as session:
        first = _snapshot(company, session)
    outcome = run_authoring(company, desk=Desk.CRYPTO, agent_handle="STRAT")
    with company.database.session() as session:
        book, _refs_ = _force_deployed(company, session, outcome.authored.version_ref)
        with pytest.raises(IntegrityViolation, match="distance between the datasets"):
            deployments(session, portfolio_ref=book, snapshot=first)


def test_a_book_with_nothing_allocated_has_no_rule_to_trade(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        snapshot = _snapshot(company, session)
        refs = _refs(company, session)
        book = open_paper_book(
            company,
            session,
            desk="crypto",
            equity=Decimal("100000"),
            opened_by=refs["portfolio"],
        )
        with pytest.raises(IntegrityViolation, match="no live allocation"):
            deployments(session, portfolio_ref=book, snapshot=snapshot)


def test_the_paper_book_is_the_only_mode_a_book_opened_here_can_have(
    company: Runtime,
) -> None:
    """There is no adapter behind any other, and ADR-0006 is why."""
    with company.database.session() as session:
        refs = _refs(company, session)
        ref = open_paper_book(
            company,
            session,
            desk="crypto",
            equity=Decimal("100000"),
            opened_by=refs["portfolio"],
        )
        again = open_paper_book(
            company,
            session,
            desk="crypto",
            equity=Decimal("100000"),
            opened_by=refs["portfolio"],
        )
        mode = session.execute(
            sa.text("SELECT mode FROM portfolios WHERE ref = :r"), {"r": ref}
        ).scalar_one()

    assert again == ref, "the desk's book is opened once and reused"
    assert mode == PortfolioMode.PAPER.value
