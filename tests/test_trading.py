"""M9: paper trading.

Three acceptance criteria from the roadmap, each with a test named after it:

* a validated strategy reaches paper only through the recorded chain,
* the gap is measured and its forecast scored,
* no module imports martex-quant's MT5 adapter (asserted in
  ``test_agents.py``, where the other ADR-0006 checks live).

The chain is proposal → assessment → approval → order → fill → position, and
the tests that matter are the ones that try to skip a link.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.alerts.service import Severity
from aurelis.core.enums import EventKind
from aurelis.core.errors import ConfigurationError, IntegrityViolation
from aurelis.core.ids import uuid7
from aurelis.org.desks import Desk
from aurelis.risk.tables import TradeProposal
from aurelis.runtime import Runtime
from aurelis.strategy.gates import default_criteria
from aurelis.strategy.states import (
    ComponentKind,
    Gate,
    Origin,
    PortfolioMode,
    StrategyState,
)
from aurelis.trading.brokers import (
    BacktestBroker,
    PaperBroker,
    SimulationBroker,
    adapters,
    resolve,
)
from aurelis.trading.cycle import GAP_QUESTION, gap_outcome, record_gap_forecast
from aurelis.trading.states import BrokerKind, OrderSide, OrderStatus
from aurelis.trading.tables import Fill, Order, Position
from aurelis.trading.triggers import verify_trading_invariants

_RATIONALE = (
    "Crowded funding marks positioning rather than information, so extremes "
    "should mean-revert once the crowd has to pay to stay in."
)
_MARK = Decimal("100")


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


def _refs(company: Runtime, session: sa.orm.Session) -> dict[str, str]:
    return {
        handle: company.roster.by_handle(session, handle).ref
        for handle in ("STRAT", "VALID", "GOV", "RISK", "PM", "TRADE")
    }


def _deployed(company: Runtime, session: sa.orm.Session) -> tuple[dict[str, str], str, str]:
    """A validated version in a paper book. The state M9 starts from."""
    refs = _refs(company, session)
    strategy = company.synthesis.open_strategy(
        session,
        name="Funding skew reversal",
        thesis="Crowded funding pays to unwind.",
        desk=Desk.CRYPTO,
        owner=refs["STRAT"],
    )
    signal = company.synthesis.author_component(
        session,
        kind=ComponentKind.SIGNAL,
        name="funding skew reversal",
        spec={"lookback": 7},
        rationale=_RATIONALE,
        origin=Origin.DERIVED_FROM_FAILURE,
        origin_ref="HYP-0001",
        author=refs["STRAT"],
        desk=Desk.CRYPTO,
    )
    composition = company.synthesis.compose(
        session,
        strategy_ref=strategy.ref,
        components=(signal,),
        universe={"desk": "crypto", "symbols": ["BTC/USDT"]},
        cost_model={"fee_bps": "10"},
        known_weaknesses=("untested through a funding regime change",),
        author=refs["STRAT"],
    )
    version_ref = composition.version.ref

    for target, reason in (
        (StrategyState.CANDIDATE, "thesis written"),
        (StrategyState.RESEARCHING, "researchers assigned"),
        (StrategyState.PROMISING, "a confirmed finding supports it"),
        (StrategyState.UNDER_REVIEW, "ready for the committee"),
    ):
        company.strategies.transition(
            session,
            strategy_ref=strategy.ref,
            target=target,
            reason=reason,
            actor=refs["STRAT"],
        )

    for gate, criterion in default_criteria("crypto").items():
        company.gates.register(
            session,
            version_ref=version_ref,
            gate=gate,
            metric=criterion["metric"],
            comparison=criterion["comparison"],
            value=criterion["value"],
            registered_by=refs["VALID"],
        )
    for gate, value in {
        Gate.A_STATISTICAL: Decimal("0.97"),
        Gate.B_BENCHMARK: Decimal("0.31"),
        Gate.C_INDEPENDENCE: Decimal("0.18"),
        Gate.D_INTEGRITY: Decimal("0"),
        Gate.E_REPLICATION: Decimal("1"),
        Gate.F_CUSTODY: Decimal("1"),
        Gate.G_CAPACITY: Decimal("1.4"),
    }.items():
        company.gates.evaluate(
            session,
            version_ref=version_ref,
            gate=gate,
            observed=value,
            evaluated_by=refs["VALID"],
        )
    company.strategies.promote(
        session,
        version_ref=version_ref,
        decided_by_meeting="MTG-0002",
        actor=refs["GOV"],
    )
    company.strategies.transition(
        session,
        strategy_ref=strategy.ref,
        target=StrategyState.PAPER_TRADING,
        reason="risk assessed and limits set",
        actor=refs["RISK"],
    )

    book = company.book.open(
        session,
        name="Crypto paper book",
        desks=("crypto",),
        mode=PortfolioMode.PAPER,
        initial_equity=Decimal("100000"),
        opened_by=refs["PM"],
    )
    company.book.allocate(
        session,
        portfolio_ref=book.ref,
        version_ref=version_ref,
        weight=Decimal("0.25"),
        rationale="first deployment at a quarter book",
        decided_by=refs["PM"],
    )
    return refs, version_ref, book.ref


def _approved(
    company: Runtime,
    session: sa.orm.Session,
    refs: dict[str, str],
    version_ref: str,
    book_ref: str,
    *,
    desired: Decimal = Decimal("1000"),
) -> str:
    proposal = TradeProposal(
        proposal_id=uuid7(),
        ref="TPR-0001",
        portfolio_ref=book_ref,
        version_ref=version_ref,
        desk="crypto",
        symbol="BTC/USDT",
        side="buy",
        desired_exposure=desired,
        rationale="signal fired at 2.4z",
        proposed_by=refs["PM"],
        proposed_at=company.clock.now(),
    )
    session.add(proposal)
    session.flush()
    company.risk.assess(session, proposal_ref=proposal.ref, assessor=refs["RISK"])
    approval = company.risk.approve(
        session, proposal_ref=proposal.ref, approver=refs["TRADE"]
    )
    return approval.ref


# --------------------------------------------- the boundary that is absent


def test_there_is_no_live_broker() -> None:
    """ADR-0006, in the vocabulary itself."""
    assert "live" not in {kind.value for kind in BrokerKind}
    assert {kind.value for kind in BrokerKind} == {"backtest", "simulation", "paper"}


def test_resolving_a_live_broker_explains_rather_than_keyerrors() -> None:
    """A KeyError reads as a typo. This has to read as a decision."""
    available = adapters()
    for name in ("live", "LIVE", "real", "production"):
        with pytest.raises(ConfigurationError, match="no live broker"):
            resolve(name, available)


def test_the_database_refuses_an_order_on_a_live_broker(company: Runtime) -> None:
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(company, session, refs, version_ref, book_ref)

    with pytest.raises(Exception, match="ck_order_has_no_live_broker"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO orders (order_id, ref, approval_ref, portfolio_ref, "
                "version_ref, desk, broker, symbol, side, quantity, "
                "expected_price, status, rejection_reason, submitted_by, "
                "submitted_at) VALUES (:i,'ORD-9999',:a,:p,:v,'crypto','live',"
                "'BTC/USDT','buy','1','1','submitted','','AG-0013',"
                "'2026-01-01 00:00:00')"
            ),
            {"i": uuid7().hex, "a": approval_ref, "p": book_ref, "v": version_ref},
        )


def test_the_three_adapters_exist_and_no_fourth() -> None:
    built = adapters(marks={"BTC/USDT": _MARK}, script=[])
    assert set(built) == {BrokerKind.BACKTEST, BrokerKind.PAPER, BrokerKind.SIMULATION}
    assert isinstance(built[BrokerKind.BACKTEST], BacktestBroker)
    assert isinstance(built[BrokerKind.PAPER], PaperBroker)


# ------------------------------------------------------------- brokers


def test_the_backtest_broker_cannot_surprise_anyone() -> None:
    """Its job is to be the baseline: no information about the world."""
    from aurelis.trading.brokers import ExecutionRequest

    broker = BacktestBroker()
    result = broker.submit(
        ExecutionRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            expected_price=Decimal("100"),
            spread_bps=Decimal("20"),
        ),
        at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    assert result.status is OrderStatus.FILLED
    assert result.price == Decimal("100.10000000")


def test_the_paper_broker_refuses_to_fill_without_an_observed_price() -> None:
    """A paper fill against an assumed price is a backtest wearing a label."""
    from aurelis.trading.brokers import ExecutionRequest

    broker = PaperBroker({})
    result = broker.submit(
        ExecutionRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            expected_price=Decimal("100"),
        ),
        at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    assert result.status is OrderStatus.REJECTED
    assert "no mark" in result.rejection_reason


def test_the_paper_broker_respects_a_limit() -> None:
    from aurelis.trading.brokers import ExecutionRequest

    broker = PaperBroker({"BTC/USDT": Decimal("100")})
    result = broker.submit(
        ExecutionRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            expected_price=Decimal("100"),
            limit_price=Decimal("99"),
        ),
        at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    assert result.status is OrderStatus.EXPIRED
    assert not result.filled


def test_an_empty_simulation_script_is_refused() -> None:
    """A scenario that invented its own fills would not be a scenario."""
    from aurelis.trading.brokers import ExecutionRequest

    with pytest.raises(ConfigurationError, match="nothing to replay"):
        SimulationBroker([]).submit(
            ExecutionRequest(
                symbol="X",
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                expected_price=Decimal("1"),
            ),
            at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )


# ------------------------ acceptance (a): only through the recorded chain


def test_an_order_requires_an_approval(company: Runtime) -> None:
    """M9 acceptance (a), through the service."""
    with company.database.session() as session:
        _deployed(company, session)
        with pytest.raises(IntegrityViolation, match="no approval"):
            company.execution.submit(
                session,
                approval_ref="TAP-9999",
                broker=PaperBroker({"BTC/USDT": _MARK}),
                symbol="BTC/USDT",
                quantity=Decimal("1"),
                expected_price=_MARK,
                submitted_by="AG-0013",
            )


def test_the_database_refuses_an_order_with_no_approval(company: Runtime) -> None:
    """M9 acceptance (a), around the runtime entirely."""
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)

    with pytest.raises(Exception, match="requires an approval|FOREIGN KEY"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO orders (order_id, ref, approval_ref, portfolio_ref, "
                "version_ref, desk, broker, symbol, side, quantity, "
                "expected_price, status, rejection_reason, submitted_by, "
                "submitted_at) VALUES (:i,'ORD-9999','TAP-9999',:p,:v,'crypto',"
                "'paper','BTC/USDT','buy','1','1','submitted','',:s,"
                "'2026-01-01 00:00:00')"
            ),
            {
                "i": uuid7().hex,
                "p": book_ref,
                "v": version_ref,
                "s": refs["TRADE"],
            },
        )


def test_an_order_may_not_exceed_what_was_approved(company: Runtime) -> None:
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(
            company, session, refs, version_ref, book_ref, desired=Decimal("500")
        )
        with pytest.raises(IntegrityViolation, match="exceeds the .* Risk approved"):
            company.execution.submit(
                session,
                approval_ref=approval_ref,
                broker=PaperBroker({"BTC/USDT": _MARK}),
                symbol="BTC/USDT",
                quantity=Decimal("100"),
                expected_price=_MARK,
                submitted_by=refs["TRADE"],
            )


def test_the_database_refuses_an_oversized_order(company: Runtime) -> None:
    """The same rule for every path that does not go through the service."""
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(
            company, session, refs, version_ref, book_ref, desired=Decimal("500")
        )

    with pytest.raises(Exception, match="may not exceed the notional Risk approved"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO orders (order_id, ref, approval_ref, portfolio_ref, "
                "version_ref, desk, broker, symbol, side, quantity, "
                "expected_price, status, rejection_reason, submitted_by, "
                "submitted_at) VALUES (:i,'ORD-9998',:a,:p,:v,'crypto','paper',"
                "'BTC/USDT','buy',100,100,'submitted','',:s,"
                "'2026-01-01 00:00:00')"
            ),
            {
                "i": uuid7().hex,
                "a": approval_ref,
                "p": book_ref,
                "v": version_ref,
                "s": refs["TRADE"],
            },
        )


def test_the_trading_triggers_are_installed(company: Runtime) -> None:
    with company.database.engine.connect() as connection:
        assert verify_trading_invariants(connection) == ()


def test_a_filled_order_moves_the_book(company: Runtime) -> None:
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(company, session, refs, version_ref, book_ref)
        executed = company.execution.submit(
            session,
            approval_ref=approval_ref,
            broker=PaperBroker({"BTC/USDT": _MARK}),
            symbol="BTC/USDT",
            quantity=Decimal("5"),
            expected_price=_MARK,
            submitted_by=refs["TRADE"],
        )
        positions = company.execution.positions(session, book_ref)

    assert executed.filled
    assert executed.order.status == OrderStatus.FILLED
    assert positions[0].symbol == "BTC/USDT"
    assert positions[0].quantity == Decimal("5")
    assert positions[0].fees_paid > 0


def test_a_rejection_is_recorded_rather_than_raised(company: Runtime) -> None:
    """A broker refusing is information about the venue or the instruction."""
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(company, session, refs, version_ref, book_ref)
        executed = company.execution.submit(
            session,
            approval_ref=approval_ref,
            broker=PaperBroker({}),
            symbol="BTC/USDT",
            quantity=Decimal("1"),
            expected_price=_MARK,
            submitted_by=refs["TRADE"],
        )
        kinds = {event.kind for event in company.ledger.tail(session, 400)}

    assert not executed.filled
    assert executed.order.status == OrderStatus.REJECTED
    assert "no mark" in executed.order.rejection_reason
    assert EventKind.ORDER_REJECTED in kinds


def test_positions_are_derived_from_fills_not_set(company: Runtime) -> None:
    """A book cannot hold something no order created."""
    from aurelis.trading.execution import Execution

    assert not hasattr(Execution, "set_position")
    methods = {name for name in dir(Execution) if not name.startswith("_")}
    assert methods == {"orders", "positions", "submit"}


def test_selling_realises_pnl_against_the_average(company: Runtime) -> None:
    """Reducing a position must not restate the basis it was built at."""
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(
            company, session, refs, version_ref, book_ref, desired=Decimal("2000")
        )
        broker = PaperBroker({"BTC/USDT": _MARK})
        company.execution.submit(
            session,
            approval_ref=approval_ref,
            broker=broker,
            symbol="BTC/USDT",
            quantity=Decimal("10"),
            expected_price=_MARK,
            submitted_by=refs["TRADE"],
            fee_bps=Decimal("0"),
            spread_bps=Decimal("0"),
        )
        opened = company.execution.positions(session, book_ref)[0]
        basis = opened.average_price

        # Sell half into a higher mark.
        proposal = TradeProposal(
            proposal_id=uuid7(),
            ref="TPR-0002",
            portfolio_ref=book_ref,
            version_ref=version_ref,
            desk="crypto",
            symbol="BTC/USDT",
            side="sell",
            desired_exposure=Decimal("2000"),
            rationale="taking half off",
            proposed_by=refs["PM"],
            proposed_at=company.clock.now(),
        )
        session.add(proposal)
        session.flush()
        company.risk.assess(session, proposal_ref="TPR-0002", assessor=refs["RISK"])
        sell_approval = company.risk.approve(
            session, proposal_ref="TPR-0002", approver=refs["TRADE"]
        )
        company.execution.submit(
            session,
            approval_ref=sell_approval.ref,
            broker=PaperBroker({"BTC/USDT": Decimal("110")}),
            symbol="BTC/USDT",
            quantity=Decimal("5"),
            expected_price=Decimal("110"),
            submitted_by=refs["TRADE"],
            fee_bps=Decimal("0"),
            spread_bps=Decimal("0"),
        )
        after = company.execution.positions(session, book_ref)[0]

    assert after.quantity == Decimal("5")
    assert after.average_price == basis, "the basis must not be restated on a sell"
    assert after.realised_pnl == Decimal("50")


# ------------------------------------------------------- post-trade


def test_slippage_and_fees_are_reported_separately(company: Runtime) -> None:
    """"Costs were higher" and "we were filled worse" have different fixes."""
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(company, session, refs, version_ref, book_ref)
        executed = company.execution.submit(
            session,
            approval_ref=approval_ref,
            broker=PaperBroker({"BTC/USDT": Decimal("101")}),
            symbol="BTC/USDT",
            quantity=Decimal("5"),
            expected_price=_MARK,
            submitted_by=refs["TRADE"],
        )
        report = company.posttrade.analyse(
            session,
            order_ref=executed.order.ref,
            analysed_by=refs["TRADE"],
            modelled_cost_bps=Decimal("15"),
        )

    assert report.slippage > 0, "filled above the expected price on a buy"
    assert report.fees > 0
    assert report.realised_cost_bps > report.slippage_bps, "fees are added on top"
    assert report.cost_surprise_bps == report.realised_cost_bps - Decimal("15")


def test_analysing_an_unfilled_order_is_refused(company: Runtime) -> None:
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(company, session, refs, version_ref, book_ref)
        executed = company.execution.submit(
            session,
            approval_ref=approval_ref,
            broker=PaperBroker({}),
            symbol="BTC/USDT",
            quantity=Decimal("1"),
            expected_price=_MARK,
            submitted_by=refs["TRADE"],
        )
        with pytest.raises(IntegrityViolation, match="has no fill"):
            company.posttrade.analyse(
                session, order_ref=executed.order.ref, analysed_by=refs["TRADE"]
            )


# ------------------- acceptance (b): the gap, measured and forecast scored


def _seed_expectation(company: Runtime, session: sa.orm.Session) -> str:
    """A completed run with a measured metric, standing in for the backtest.

    Produced through the research lifecycle rather than inserted, so the
    expectation the gap cites is a real result row with a real artifact digest.
    """
    from aurelis.research.review import survivorship_claim

    refs = _refs(company, session)
    quant = company.roster.by_handle(session, "QUANT").ref
    hypothesis = company.research.propose(
        session,
        claim="A rotation keeps drawdown below 20%.",
        author=quant,
        minimum_effect=Decimal("0.11"),
        primary_metric="max_drawdown",
        family="strategy.rotation.crypto",
        desk="crypto",
    )
    company.research.screen(session, hypothesis.ref)
    registration = company.research.register(
        session,
        hypothesis_ref=hypothesis.ref,
        spec=survivorship_claim(200),
        registrar=refs["GOV"],
        pass_criteria=[
            {"metric": "max_drawdown", "comparison": "lt", "value": "0.20", "on": "point"}
        ],
    )
    experiment = company.research.design(
        session, registration_ref=registration.ref, designer=quant
    )
    run, _artifact = company.research.execute(session, experiment_ref=experiment.ref)
    return run.ref


def test_the_gap_cites_the_number_that_justified_deployment(
    company: Runtime,
) -> None:
    """M9 acceptance (b), first half.

    The expectation is copied from the run that supported the promotion, with
    its artifact digest — not recomputed. Re-deriving it would compare paper
    against today's estimate instead of against the claim that was actually
    made.
    """
    with company.database.session() as session:
        _refs(company, session)
        _deployed(company, session)
        run_ref = _seed_expectation(company, session)
        expected, digest = company.posttrade.expectation(
            session, run_ref=run_ref, metric="max_drawdown"
        )

    assert expected > 0
    assert len(digest) == 64, "the expectation cites an artifact"


def test_a_gap_that_falls_short_is_recorded_as_falling_short(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        _refs(company, session)
        _refs_, version_ref, book_ref = _deployed(company, session)
        run_ref = _seed_expectation(company, session)
        expected, _ = company.posttrade.expectation(
            session, run_ref=run_ref, metric="max_drawdown"
        )
        gap = company.posttrade.measure_gap(
            session,
            version_ref=version_ref,
            portfolio_ref=book_ref,
            desk="crypto",
            metric="max_drawdown",
            run_ref=run_ref,
            realised=expected + Decimal("0.05"),
            period_start=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            period_end=dt.datetime(2026, 1, 31, tzinfo=dt.UTC),
            observations=30,
            realised_source="paper cycle",
        )
        kinds = {event.kind for event in company.ledger.tail(session, 500)}

    # A *deeper* drawdown than the backtest promised is falling short. The
    # direction matters: the same arithmetic on Sharpe would mean the opposite.
    assert gap.gap == Decimal("0.05")
    assert not gap.held
    assert "fell short" in gap.describe()
    assert EventKind.GAP_MEASURED in kinds


def test_a_gap_is_measured_once_per_period(company: Runtime) -> None:
    with company.database.session() as session:
        _refs_, version_ref, book_ref = _deployed(company, session)
        run_ref = _seed_expectation(company, session)
        period_end = dt.datetime(2026, 1, 31, tzinfo=dt.UTC)
        for realised in (Decimal("0.1"), Decimal("0.9")):
            company.posttrade.measure_gap(
                session,
                version_ref=version_ref,
                portfolio_ref=book_ref,
                desk="crypto",
                metric="max_drawdown",
                run_ref=run_ref,
                realised=realised,
                period_start=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                period_end=period_end,
                observations=30,
                realised_source="paper cycle",
            )
        rows = company.posttrade.gaps(session, version_ref=version_ref)

    assert len(rows) == 1, "a period is measured once; a second call returns the first"
    assert rows[0].realised == Decimal("0.1")


def test_the_company_gap_is_a_company_competence(company: Runtime) -> None:
    """How wrong our backtests tend to be is a fact about us."""
    with company.database.session() as session:
        _refs_, version_ref, book_ref = _deployed(company, session)
        run_ref = _seed_expectation(company, session)
        expected, _ = company.posttrade.expectation(
            session, run_ref=run_ref, metric="max_drawdown"
        )
        assert company.posttrade.company_gap(session, "max_drawdown") is None

        for index, delta in enumerate((Decimal("0.04"), Decimal("0.06"))):
            company.posttrade.measure_gap(
                session,
                version_ref=version_ref,
                portfolio_ref=book_ref,
                desk="crypto",
                metric="max_drawdown",
                run_ref=run_ref,
                realised=expected + delta,
                period_start=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                period_end=dt.datetime(2026, 2 + index, 1, tzinfo=dt.UTC),
                observations=30,
                realised_source="paper cycle",
            )
        mean = company.posttrade.company_gap(session, "max_drawdown")

    assert mean == Decimal("0.05000000")


def test_a_deployment_forecast_is_recorded_and_scored(company: Runtime) -> None:
    """M9 acceptance (b), second half.

    Every deployment forecasts whether its own backtest will hold, and the
    first completed period scores it. Over deployments that produces a
    calibration for the claim the company makes most often and checks least.
    """
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        run_ref = _seed_expectation(company, session)
        expected, _ = company.posttrade.expectation(
            session, run_ref=run_ref, metric="max_drawdown"
        )

        forecast = record_gap_forecast(
            session,
            meeting_ref="MTG-0002",
            agent_ref=refs["VALID"],
            probability=Decimal("0.7"),
            reasoning="costs were modelled generously and the universe is small",
            at=company.clock.now(),
        )
        assert forecast.question == GAP_QUESTION
        assert forecast.brier is None

        gap = company.posttrade.measure_gap(
            session,
            version_ref=version_ref,
            portfolio_ref=book_ref,
            desk="crypto",
            metric="max_drawdown",
            run_ref=run_ref,
            realised=expected + Decimal("0.05"),
            period_start=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            period_end=dt.datetime(2026, 1, 31, tzinfo=dt.UTC),
            observations=30,
            realised_source="paper cycle",
        )
        scored = company.forecasts.score(
            session,
            meeting_ref="MTG-0002",
            outcome=gap_outcome((gap,)),
            against=version_ref,
        )

    assert not gap_outcome((gap,)), "the gap fell short, so the forecast was wrong"
    assert len(scored) == 1
    assert scored[0].outcome is False
    assert scored[0].brier == Decimal("0.49"), "0.7 confident and wrong"
    assert scored[0].scored_against == version_ref


def test_a_gap_holds_only_when_every_metric_held() -> None:
    """A return that held while drawdown blew out did not meet expectation."""
    from aurelis.trading.posttrade import Gap

    held = Gap("SV-1", "total_return", Decimal("1"), Decimal("2"), 30, "d")
    missed = Gap("SV-1", "max_drawdown", Decimal("0.1"), Decimal("0.3"), 30, "d")

    assert gap_outcome((held,))
    assert not gap_outcome((held, missed))
    assert not gap_outcome(()), "no measurement is not a success"


# ------------------------------------------------------- the paper cycle


def test_the_paper_cycle_runs_the_whole_chain(company: Runtime) -> None:
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        outcome = company.cycle.run(
            session,
            portfolio_ref=book_ref,
            broker=PaperBroker({"BTC/USDT": _MARK}),
            intents=(
                (version_ref, "BTC/USDT", OrderSide.BUY, Decimal("1000"), _MARK),
            ),
            proposer=refs["PM"],
            assessor=refs["RISK"],
            approver=refs["TRADE"],
            executor=refs["TRADE"],
            analyst=refs["TRADE"],
        )
        orders = company.execution.orders(session, book_ref)
        kinds = {event.kind for event in company.ledger.tail(session, 500)}

    assert outcome.executed == 1
    assert not outcome.refused
    assert len(orders) == 1
    assert orders[0].broker == BrokerKind.PAPER.value
    assert EventKind.PAPER_CYCLE_RAN in kinds
    assert EventKind.POST_TRADE_ANALYSED in kinds


def test_a_vetoed_intent_never_becomes_an_order_and_raises_an_alert(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        company.risk.set_limit(
            session,
            scope="desk",
            scope_id="crypto",
            metric="exposure",
            bound=Decimal("0"),
            reason="desk paused pending a data review",
            set_by=refs["RISK"],
        )
        outcome = company.cycle.run(
            session,
            portfolio_ref=book_ref,
            broker=PaperBroker({"BTC/USDT": _MARK}),
            intents=(
                (version_ref, "BTC/USDT", OrderSide.BUY, Decimal("1000"), _MARK),
            ),
            proposer=refs["PM"],
            assessor=refs["RISK"],
            approver=refs["TRADE"],
            executor=refs["TRADE"],
            analyst=refs["TRADE"],
        )
        orders = company.execution.orders(session, book_ref)
        open_alerts = company.alerts.open(session)

    assert outcome.executed == 0
    assert len(outcome.refused) == 1
    assert orders == []
    assert len(open_alerts) == 1
    assert open_alerts[0].severity == Severity.WARNING.value
    assert open_alerts[0].recommended_action


def test_a_halted_desk_stops_the_cycle_without_an_order(company: Runtime) -> None:
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        company.risk.latch(
            session,
            scope="desk",
            scope_id="crypto",
            tripwire="drawdown_floor",
            observed="-0.31",
            threshold="-0.25",
            detail="paper drawdown breached the preregistered floor",
        )
        outcome = company.cycle.run(
            session,
            portfolio_ref=book_ref,
            broker=PaperBroker({"BTC/USDT": _MARK}),
            intents=(
                (version_ref, "BTC/USDT", OrderSide.BUY, Decimal("1000"), _MARK),
            ),
            proposer=refs["PM"],
            assessor=refs["RISK"],
            approver=refs["TRADE"],
            executor=refs["TRADE"],
            analyst=refs["TRADE"],
        )
        orders = company.execution.orders(session, book_ref)

    assert outcome.executed == 0
    assert orders == []
    assert any("halt" in note for note in outcome.notes)


# ------------------------------------------------------------- alerts


def test_an_alert_must_say_what_to_do(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        with pytest.raises(IntegrityViolation, match="must say what to do"):
            company.alerts.raise_alert(
                session,
                severity=Severity.WARNING,
                source="test",
                message="something is wrong",
                recommended_action="   ",
                raised_by=refs["RISK"],
            )


def test_alerts_deduplicate_while_unresolved(company: Runtime) -> None:
    """A monitor firing every cycle should produce one open alert."""
    with company.database.session() as session:
        refs = _refs(company, session)
        for _ in range(5):
            company.alerts.raise_alert(
                session,
                severity=Severity.WARNING,
                source="trading.paper_cycle",
                subject="SV-0001",
                message="risk shrank the intent again",
                recommended_action="review the desk limit",
                raised_by=refs["RISK"],
            )
        assert len(company.alerts.open(session)) == 1


def test_looking_and_fixing_are_different_acts(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        alert = company.alerts.raise_alert(
            session,
            severity=Severity.CRITICAL,
            source="risk.kill",
            message="drawdown floor breached",
            recommended_action="review what died before clearing the latch",
            raised_by=refs["RISK"],
        )
        assert company.alerts.unacknowledged(session) == [alert]

        company.alerts.acknowledge(session, alert.ref, by=refs["GOV"])
        acknowledged = company.alerts.open(session)[0]
        assert acknowledged.acknowledged_at is not None
        assert acknowledged.resolved_at is None, "looking is not fixing"

        company.alerts.resolve(
            session,
            alert.ref,
            resolution="latch cleared by the operator after review",
            by=refs["GOV"],
        )
        assert company.alerts.open(session) == []


def test_the_database_refuses_a_resolution_nobody_looked_at(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)

    with pytest.raises(Exception, match="ck_alert_resolved_only_after_acknowledged"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO alerts (alert_id, ref, severity, source, message, "
                "recommended_action, evidence, raised_by, raised_at, resolved_at, "
                "resolution) VALUES (:i,'ALT-9999','warning','x','y','do this',"
                "'{}',:a,'2026-01-01 00:00:00','2026-01-02 00:00:00','done')"
            ),
            {"i": uuid7().hex, "a": refs["RISK"]},
        )


# ---------------------------------------------- separation of duties


def test_the_execution_chain_is_four_different_scopes(company: Runtime) -> None:
    """The agent that wants the exposure is not the one that approves it."""
    from aurelis.agents.guards import SCOPE_GUARDS

    guarded = {guard.table: guard.scope.value for guard in SCOPE_GUARDS}
    assert guarded["trade_proposals"] == "trade_proposal"
    assert guarded["risk_assessments"] == "risk_assessment"
    assert guarded["trade_approvals"] == "trade_approval"
    assert guarded["orders"] == "order"
    assert len({guarded[t] for t in
                ("trade_proposals", "risk_assessments", "trade_approvals", "orders")}) == 4


def test_an_agent_without_the_order_scope_cannot_submit_one(
    company: Runtime,
) -> None:
    """Enforced by the database, not by the execution service.

    The guard fires during the flush, which poisons the session — so the whole
    block is inside ``raises``. That is the honest shape: a refused write is
    not something the caller carries on from.
    """
    raises = pytest.raises(Exception, match="may not write order")
    with raises, company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(company, session, refs, version_ref, book_ref)
        company.execution.submit(
            session,
            approval_ref=approval_ref,
            broker=PaperBroker({"BTC/USDT": _MARK}),
            symbol="BTC/USDT",
            quantity=Decimal("1"),
            expected_price=_MARK,
            submitted_by=refs["STRAT"],
        )


def test_the_trading_tables_are_in_the_declared_schema() -> None:
    import aurelis.alerts.tables as alert_tables
    import aurelis.trading.tables as trading_tables
    from aurelis.schema import TABLE_MODULES

    assert trading_tables in TABLE_MODULES
    assert alert_tables in TABLE_MODULES


def test_the_runtime_exposes_the_trading_layer(company: Runtime) -> None:
    assert company.execution is not None
    assert company.posttrade is not None
    assert company.cycle is not None
    assert company.alerts is not None
    assert set(company.brokers) == {BrokerKind.BACKTEST, BrokerKind.PAPER}


def test_a_position_and_fill_exist_for_every_filled_order(company: Runtime) -> None:
    with company.database.session() as session:
        refs, version_ref, book_ref = _deployed(company, session)
        approval_ref = _approved(company, session, refs, version_ref, book_ref)
        company.execution.submit(
            session,
            approval_ref=approval_ref,
            broker=PaperBroker({"BTC/USDT": _MARK}),
            symbol="BTC/USDT",
            quantity=Decimal("2"),
            expected_price=_MARK,
            submitted_by=refs["TRADE"],
        )
        orders = list(session.execute(sa.select(Order)).scalars())
        fills = list(session.execute(sa.select(Fill)).scalars())
        positions = list(session.execute(sa.select(Position)).scalars())

    assert len(orders) == len(fills) == len(positions) == 1
    assert fills[0].order_ref == orders[0].ref


def test_gap_direction_is_read_from_the_metric_not_the_sign(company: Runtime) -> None:
    """A lower drawdown is better; a lower Sharpe is not.

    An earlier version compared ``realised - expected >= 0`` for every metric
    and reported a deployment that beat its drawdown estimate as having fallen
    short. The direction table is what stops that.
    """
    from aurelis.trading.posttrade import DIRECTIONS, Direction, Gap

    beat_drawdown = Gap("SV-1", "max_drawdown", Decimal("0.2"), Decimal("0.1"), 30, "d")
    missed_sharpe = Gap("SV-1", "sharpe", Decimal("1.0"), Decimal("0.4"), 30, "d")

    assert beat_drawdown.gap < 0 and beat_drawdown.held
    assert missed_sharpe.gap < 0 and not missed_sharpe.held
    assert DIRECTIONS["max_drawdown"] is Direction.LOWER_IS_BETTER
    assert DIRECTIONS["sharpe"] is Direction.HIGHER_IS_BETTER


def test_a_metric_with_no_recorded_direction_raises(company: Runtime) -> None:
    """Guessing is how a beaten estimate gets recorded as a miss."""
    from aurelis.trading.posttrade import Gap

    unknown = Gap("SV-1", "invented_metric", Decimal("1"), Decimal("2"), 30, "d")
    with pytest.raises(IntegrityViolation, match="no direction is recorded"):
        _ = unknown.held


def test_a_descriptive_metric_has_a_gap_but_no_verdict(company: Runtime) -> None:
    from aurelis.trading.posttrade import Gap

    descriptive = Gap("SV-1", "n_trades", Decimal("40"), Decimal("52"), 30, "d")
    assert descriptive.gap == Decimal("12")
    assert "descriptive" in descriptive.describe()
    with pytest.raises(IntegrityViolation, match="'held' is not a question"):
        _ = descriptive.held
