"""M8: strategy, portfolio and risk.

Three acceptance criteria from the roadmap, each with a test named after it:

* modifying a ``VALIDATED`` version is refused by the database and becomes a
  new version at ``UNDER_REVIEW``,
* a trade proposal without a risk assessment cannot be approved,
* a strategy that passes solo and fails gate C is blocked, with the correlation
  evidence on the record.

And one the roadmap does not state but the project turns on: a strategy is
**composed from authored components**, never promoted from a result. The tests
under "creation, not selection" are the ones that would fail if this layer ever
became a selection engine.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import uuid7
from aurelis.org.desks import Desk
from aurelis.portfolio.construction import correlation
from aurelis.risk.tables import TradeProposal
from aurelis.runtime import Runtime
from aurelis.strategy.gates import default_criteria
from aurelis.strategy.markets import Assumption, profile, unmet_assumptions
from aurelis.strategy.states import (
    ComponentKind,
    Gate,
    Origin,
    Portability,
    PortfolioMode,
    RiskDecision,
    StrategyState,
)
from aurelis.strategy.tables import Component, StrategyVersion
from aurelis.strategy.triggers import verify_strategy_invariants

_RATIONALE = (
    "Crowded funding marks positioning rather than information, so extremes "
    "should mean-revert once the crowd has to pay to stay in."
)


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


def _refs(company: Runtime, session: sa.orm.Session) -> dict[str, str]:
    return {
        handle: company.roster.by_handle(session, handle).ref
        for handle in ("STRAT", "VALID", "QUANT", "GOV", "RISK", "PM", "TRADE", "CRITIC")
    }


def _signal(
    company: Runtime,
    session: sa.orm.Session,
    author: str,
    *,
    name: str = "funding skew reversal",
    origin: Origin = Origin.DERIVED_FROM_FAILURE,
    origin_ref: str = "HYP-0001",
    assumes: tuple[str, ...] = (),
    desk: Desk = Desk.CRYPTO,
) -> Component:
    return company.synthesis.author_component(
        session,
        kind=ComponentKind.SIGNAL,
        name=name,
        spec={"lookback": 7},
        rationale=_RATIONALE,
        origin=origin,
        origin_ref=origin_ref,
        author=author,
        desk=desk,
        assumes=assumes,
    )


def _sizing(company: Runtime, session: sa.orm.Session, author: str) -> Component:
    return company.synthesis.author_component(
        session,
        kind=ComponentKind.SIZING,
        name="inverse vol sizing",
        spec={"target_vol": "0.15"},
        rationale=(
            "Equal notional over-weights whichever name is currently wildest, "
            "which is a leverage decision nobody actually made."
        ),
        origin=Origin.INVENTED,
        origin_ref="MTG-0001",
        author=author,
        desk=Desk.CRYPTO,
    )


def _compose(
    company: Runtime,
    session: sa.orm.Session,
    refs: dict[str, str],
    *,
    assumes: tuple[str, ...] = (),
) -> str:
    strategy = company.synthesis.open_strategy(
        session,
        name="Funding skew reversal",
        thesis="Crowded funding pays to unwind.",
        desk=Desk.CRYPTO,
        owner=refs["STRAT"],
    )
    signal = _signal(company, session, refs["STRAT"], assumes=assumes)
    sizing = _sizing(company, session, refs["STRAT"])
    composition = company.synthesis.compose(
        session,
        strategy_ref=strategy.ref,
        components=(signal, sizing),
        universe={"desk": "crypto", "symbols": ["BTC/USDT"]},
        cost_model={"fee_bps": "10"},
        known_weaknesses=("untested through a funding regime change",),
        author=refs["STRAT"],
        meeting_ref="MTG-0001",
    )
    _advance_to_review(company, session, strategy.ref, refs["STRAT"])
    return composition.version.ref


def _advance_to_review(
    company: Runtime, session: sa.orm.Session, strategy_ref: str, actor: str
) -> None:
    """Walk a strategy through its lifecycle to UNDER_REVIEW.

    Written out rather than short-circuited because each of these transitions
    has a real requirement behind it, and a test that jumped straight to
    review would be exercising a path the company does not have.
    """
    for target, reason in (
        (StrategyState.CANDIDATE, "thesis written and a desk chosen"),
        (StrategyState.RESEARCHING, "project accepted, researchers assigned"),
        (StrategyState.PROMISING, "a confirmed finding supports the thesis"),
        (StrategyState.UNDER_REVIEW, "gates registered; ready for the committee"),
    ):
        company.strategies.transition(
            session,
            strategy_ref=strategy_ref,
            target=target,
            reason=reason,
            actor=actor,
        )


def _pass_every_gate(
    company: Runtime,
    session: sa.orm.Session,
    version_ref: str,
    gov: str,
    *,
    overrides: dict[Gate, Decimal] | None = None,
) -> None:
    for gate, criterion in default_criteria("crypto").items():
        company.gates.register(
            session,
            version_ref=version_ref,
            gate=gate,
            metric=criterion["metric"],
            comparison=criterion["comparison"],
            value=criterion["value"],
            registered_by=gov,
        )
    observed = {
        Gate.A_STATISTICAL: Decimal("0.97"),
        Gate.B_BENCHMARK: Decimal("0.31"),
        Gate.C_INDEPENDENCE: Decimal("0.18"),
        Gate.D_INTEGRITY: Decimal("0"),
        Gate.E_REPLICATION: Decimal("1"),
        Gate.F_CUSTODY: Decimal("1"),
        Gate.G_CAPACITY: Decimal("1.4"),
    }
    observed.update(overrides or {})
    for gate, value in observed.items():
        company.gates.evaluate(
            session,
            version_ref=version_ref,
            gate=gate,
            observed=value,
            evaluated_by=gov,
        )


# ------------------------------------------- creation, not selection


def test_nothing_here_turns_a_hypothesis_into_a_strategy(company: Runtime) -> None:
    """The project's premise, asserted against the API surface.

    If a promote-from-result function ever appears, the company becomes a
    selection engine: it produces what its corpus already contains and stops
    when the corpus runs out.
    """
    import aurelis.strategy as strategy_package
    from aurelis.strategy import synthesis

    names = set(dir(synthesis.Synthesis)) | set(strategy_package.__all__)
    forbidden = {"promote_hypothesis", "from_hypothesis", "from_finding", "adopt"}
    assert not (names & forbidden)

    columns = {column.name for column in StrategyVersion.__table__.columns}
    assert "hypothesis_ref" not in columns
    assert "finding_ref" not in columns


def test_a_component_must_state_why_it_should_work(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        with pytest.raises(IntegrityViolation, match="must state why it should work"):
            company.synthesis.author_component(
                session,
                kind=ComponentKind.SIGNAL,
                name="thing",
                spec={},
                rationale="works",
                origin=Origin.INVENTED,
                origin_ref="MTG-0001",
                author=refs["STRAT"],
                desk=Desk.CRYPTO,
            )


def test_an_invented_component_may_not_cite_inherited_work(company: Runtime) -> None:
    """"We created this" has to be falsifiable, so the citation shape is checked."""
    with company.database.session() as session:
        refs = _refs(company, session)
        with pytest.raises(IntegrityViolation, match="must cite one of"):
            _signal(
                company,
                session,
                refs["STRAT"],
                origin=Origin.INVENTED,
                origin_ref="MQ-H11",
            )


def test_the_database_refuses_a_component_with_no_origin(company: Runtime) -> None:
    """The same rule, around the runtime entirely.

    Written by an agent that genuinely holds the scope, so the CHECK is what
    refuses it rather than the write-scope guard firing first.
    """
    with company.database.session() as session:
        author = _refs(company, session)["STRAT"]

    with pytest.raises(Exception, match="ck_component_cites_its_origin"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO components (component_id, ref, kind, name, spec, "
                "spec_digest, rationale, origin, origin_ref, author, desk, "
                "assumes, retired_reason, created_at) VALUES "
                "(:i,'CMP-9999','signal','x','{}','d','because','invented','   ',"
                ":a,'crypto','[]','','2026-01-01 00:00:00')"
            ),
            {"i": uuid7().hex, "a": author},
        )


def test_novelty_counts_origins_rather_than_claiming_them(company: Runtime) -> None:
    """The measured answer to "did the agents create this?"."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        novelty = company.synthesis.novelty(session, version_ref)

    assert novelty.total == 2
    assert novelty.authored == 2
    assert novelty.inherited == 0
    assert "2 of 2 component(s) authored here" in novelty.describe()


def test_an_inherited_composition_reads_as_inherited(company: Runtime) -> None:
    """Adapting prior art is legitimate; claiming it as invention is not."""
    with company.database.session() as session:
        refs = _refs(company, session)
        strategy = company.synthesis.open_strategy(
            session,
            name="Adapted rotation",
            thesis="The inherited rotation, re-costed.",
            desk=Desk.CRYPTO,
            owner=refs["STRAT"],
        )
        borrowed = _signal(
            company,
            session,
            refs["STRAT"],
            name="cross-sectional rotation",
            origin=Origin.ADAPTED,
            origin_ref="MQ-H11",
        )
        composition = company.synthesis.compose(
            session,
            strategy_ref=strategy.ref,
            components=(borrowed,),
            universe={"desk": "crypto"},
            cost_model={"fee_bps": "10"},
            known_weaknesses=("inherited, and not re-derived",),
            author=refs["STRAT"],
        )
        novelty = company.synthesis.novelty(session, composition.version.ref)

    assert novelty.authored == 0
    assert novelty.inherited == 1


def test_a_composition_needs_an_idea_in_it(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        strategy = company.synthesis.open_strategy(
            session,
            name="Sizing only",
            thesis="No idea, just sizing.",
            desk=Desk.CRYPTO,
            owner=refs["STRAT"],
        )
        sizing = _sizing(company, session, refs["STRAT"])
        with pytest.raises(IntegrityViolation, match="at least one signal"):
            company.synthesis.compose(
                session,
                strategy_ref=strategy.ref,
                components=(sizing,),
                universe={},
                cost_model={},
                known_weaknesses=("none known",),
                author=refs["STRAT"],
            )


def test_authors_must_name_a_weakness(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        strategy = company.synthesis.open_strategy(
            session,
            name="Perfect",
            thesis="Nothing wrong with it.",
            desk=Desk.CRYPTO,
            owner=refs["STRAT"],
        )
        signal = _signal(company, session, refs["STRAT"])
        with pytest.raises(IntegrityViolation, match="known weakness"):
            company.synthesis.compose(
                session,
                strategy_ref=strategy.ref,
                components=(signal,),
                universe={},
                cost_model={},
                known_weaknesses=(),
                author=refs["STRAT"],
            )


def test_lineage_records_what_was_done_and_by_whom(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        first = _compose(company, session, refs)
        original = company.synthesis.components_of(session, first)[0]
        replacement = _signal(
            company,
            session,
            refs["STRAT"],
            name="funding skew, basis-neutralised",
            origin=Origin.REFINED,
            origin_ref=original.ref,
        )
        composition = company.synthesis.mutate(
            session,
            version_ref=first,
            replace=original,
            with_component=replacement,
            author=refs["STRAT"],
            reason="decorrelate from the deployed book",
            meeting_ref="MTG-0002",
        )
        second = composition.version.ref
        ancestry = company.synthesis.ancestry(session, second)
        lineage = company.synthesis.lineage_of(session, second)

    assert ancestry == (first, second)
    assert lineage[0].act == "mutated"
    assert lineage[0].parent_ref == first
    assert "decorrelate" in lineage[0].detail
    assert lineage[0].meeting_ref == "MTG-0002"


def test_a_mutation_must_say_what_it_is_fixing(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        original = company.synthesis.components_of(session, version_ref)[0]
        replacement = _sizing(company, session, refs["STRAT"])
        with pytest.raises(IntegrityViolation, match="must say what it is trying to fix"):
            company.synthesis.mutate(
                session,
                version_ref=version_ref,
                replace=original,
                with_component=replacement,
                author=refs["STRAT"],
                reason="  ",
            )


# ----------------------------------------------- seven markets, not one


def test_market_profiles_are_derived_from_the_desk_registry() -> None:
    """A second table of market facts would disagree with the first."""
    crypto = profile(Desk.CRYPTO)
    equities = profile(Desk.EQUITIES)

    assert crypto.meets(Assumption.PERPETUAL_FUNDING)
    assert crypto.meets(Assumption.CONTINUOUS_TRADING)
    assert not equities.meets(Assumption.PERPETUAL_FUNDING)
    assert equities.meets(Assumption.SESSION_CALENDAR)
    assert equities.meets(Assumption.FUNDAMENTALS)


def test_every_desk_has_a_profile() -> None:
    for desk in Desk:
        assert profile(desk).provides, desk


def test_a_funding_signal_is_inapplicable_off_a_perpetual_market(
    company: Runtime,
) -> None:
    """The corpus is crypto-only. This is where that stops being invisible."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs, assumes=("perpetual_funding",))
        portability = company.synthesis.check_portability(session, version_ref)

    assert portability[Desk.CRYPTO][0] == Portability.NATIVE.value
    for desk in (Desk.EQUITIES, Desk.OPTIONS, Desk.FUTURES, Desk.FX):
        status, reason = portability[desk]
        assert status == Portability.INAPPLICABLE.value, desk
        assert "perpetual_funding" in reason


def test_a_portable_version_is_unproven_elsewhere_until_measured(
    company: Runtime,
) -> None:
    """Unproven is the default, and it is not the same as working."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        rows = {
            row.desk: row.status
            for row in company.strategies.portability(session, version_ref)
        }

    assert rows["crypto"] == Portability.NATIVE.value
    assert set(rows) == {desk.value for desk in Desk}
    assert all(
        status == Portability.UNPROVEN.value
        for desk, status in rows.items()
        if desk != "crypto"
    )


def test_claiming_a_desk_works_requires_evidence_from_that_desk(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        with pytest.raises(IntegrityViolation, match="requires evidence from a run"):
            company.strategies.record_portability(
                session,
                version_ref=version_ref,
                desk="equities",
                status=Portability.PORTED,
                reason="momentum is universal",
            )


def test_proven_desks_lists_only_what_was_measured(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        company.strategies.record_portability(
            session,
            version_ref=version_ref,
            desk="equities",
            status=Portability.REFUTED_HERE,
            reason="the effect inverts across the close",
            evidence_ref="RUN-0002",
        )
        proven = company.strategies.proven_desks(session, version_ref)

    assert proven == ("crypto",)


def test_a_component_cannot_be_composed_onto_a_desk_that_lacks_its_assumption(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        strategy = company.synthesis.open_strategy(
            session,
            name="Equity funding",
            thesis="A funding signal, on equities.",
            desk=Desk.EQUITIES,
            owner=refs["STRAT"],
        )
        signal = _signal(
            company,
            session,
            refs["STRAT"],
            assumes=("perpetual_funding",),
            desk=Desk.EQUITIES,
        )
        with pytest.raises(IntegrityViolation, match="do not fit this desk"):
            company.synthesis.compose(
                session,
                strategy_ref=strategy.ref,
                components=(signal,),
                universe={},
                cost_model={},
                known_weaknesses=("wrong market",),
                author=refs["STRAT"],
            )


def test_unmet_assumptions_ignores_names_it_cannot_evaluate() -> None:
    assert unmet_assumptions(Desk.EQUITIES, ("nonsense",)) == ()
    assert unmet_assumptions(Desk.EQUITIES, ("perpetual_funding",)) == (
        Assumption.PERPETUAL_FUNDING,
    )


def test_a_component_may_not_declare_an_uncheckable_assumption(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        with pytest.raises(IntegrityViolation, match="market model does not know"):
            _signal(company, session, refs["STRAT"], assumes=("lunar_cycle",))


# ------------------------------------------------------------- gates


def test_a_gate_cannot_be_registered_twice(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        company.gates.register(
            session,
            version_ref=version_ref,
            gate=Gate.A_STATISTICAL,
            metric="deflated_sharpe",
            comparison="gte",
            value=Decimal("0.95"),
            registered_by=refs["VALID"],
        )
        with pytest.raises(IntegrityViolation, match="already registered"):
            company.gates.register(
                session,
                version_ref=version_ref,
                gate=Gate.A_STATISTICAL,
                metric="deflated_sharpe",
                comparison="gte",
                value=Decimal("0.50"),
                registered_by=refs["VALID"],
            )


def test_an_unregistered_gate_cannot_be_evaluated(company: Runtime) -> None:
    """A criterion written now would be chosen knowing the answer."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        with pytest.raises(IntegrityViolation, match="never registered"):
            company.gates.evaluate(
                session,
                version_ref=version_ref,
                gate=Gate.A_STATISTICAL,
                observed=Decimal("0.99"),
                evaluated_by=refs["VALID"],
            )


def test_promotion_needs_every_registered_gate_evaluated(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
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
        outcome = company.strategies.promote(
            session,
            version_ref=version_ref,
            decided_by_meeting="MTG-0002",
            actor=refs["GOV"],
        )

    assert not isinstance(outcome, StrategyVersion)
    assert "not evaluated" in outcome.reason


def test_the_strategy_triggers_are_installed(company: Runtime) -> None:
    with company.database.engine.connect() as connection:
        assert verify_strategy_invariants(connection) == ()


# ------------------------------------------- acceptance (c): gate C


def test_a_strategy_that_passes_solo_and_fails_gate_c_is_blocked(
    company: Runtime,
) -> None:
    """M8 acceptance (c).

    The best individual strategy is not automatically a portfolio component.
    Every other gate passes; the correlation with the deployed book does not,
    and the evidence stays on the record.
    """
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _pass_every_gate(
            company,
            session,
            version_ref,
            refs["VALID"],
            overrides={Gate.C_INDEPENDENCE: Decimal("0.83")},
        )
        outcome = company.strategies.promote(
            session,
            version_ref=version_ref,
            decided_by_meeting="MTG-0002",
            actor=refs["GOV"],
        )
        report = company.gates.report(session, version_ref)
        version = company.strategies.version(session, version_ref)

    assert not isinstance(outcome, StrategyVersion)
    assert outcome.reason == "gate(s) C failed"
    assert version.promoted_at is None
    assert version.state == StrategyState.UNDER_REVIEW

    failed = report.failed
    assert [o.gate for o in failed] == [Gate.C_INDEPENDENCE]
    assert "0.83" in failed[0].detail
    assert "lt 0.5" in failed[0].detail
    assert [o.passed for o in report.outcomes].count(True) == 6


def test_correlation_is_measured_not_assumed(company: Runtime) -> None:
    """Gate C's number comes from returns the engines produced."""
    rising = [Decimal(str(x)) for x in (1, 2, 3, 4, 5)]
    falling = [Decimal(str(-x)) for x in (1, 2, 3, 4, 5)]

    assert correlation(rising, rising) == Decimal("1")
    assert correlation(rising, falling) == Decimal("-1")
    assert correlation(rising, [Decimal("1")] * 5) is None, "a flat series has no answer"
    assert correlation(rising, rising[:1]) is None


def test_the_book_measures_correlation_against_its_members(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        first = _compose(company, session, refs)
        _pass_every_gate(company, session, first, refs["VALID"])
        company.strategies.promote(
            session,
            version_ref=first,
            decided_by_meeting="MTG-0002",
            actor=refs["GOV"],
        )
        book = company.book.open(
            session,
            name="Crypto book",
            desks=("crypto",),
            mode=PortfolioMode.PAPER,
            initial_equity=Decimal("100000"),
            opened_by=refs["PM"],
        )
        company.book.allocate(
            session,
            portfolio_ref=book.ref,
            version_ref=first,
            weight=Decimal("0.25"),
            rationale="first deployment at a quarter book",
            decided_by=refs["PM"],
        )
        returns = {
            first: [Decimal(str(x)) for x in (1, -1, 2, -2, 3)],
            "SV-CANDIDATE": [Decimal(str(x)) for x in (1, -1, 2, -2, 3)],
        }
        correlations = company.book.correlations(
            session, book.ref, returns=returns, candidate="SV-CANDIDATE"
        )
        strongest = correlations.max_against("SV-CANDIDATE")
        snapshot = company.book.snapshot(
            session, portfolio_ref=book.ref, correlations=correlations
        )

    assert strongest is not None
    assert strongest[0] == first
    assert strongest[1] == Decimal("1")
    assert snapshot.correlation_digest
    assert snapshot.concentration == Decimal("0.25")


def test_an_empty_book_has_nothing_to_be_independent_of(company: Runtime) -> None:
    """Not the same as uncorrelated, and the type says so."""
    with company.database.session() as session:
        refs = _refs(company, session)
        book = company.book.open(
            session,
            name="Empty",
            desks=("crypto",),
            mode=PortfolioMode.BACKTEST,
            initial_equity=Decimal("1000"),
            opened_by=refs["PM"],
        )
        correlations = company.book.correlations(
            session, book.ref, returns={}, candidate="SV-0001"
        )

    assert correlations.max_against("SV-0001") is None


def test_a_book_may_not_be_allocated_past_one(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        book = company.book.open(
            session,
            name="Crypto book",
            desks=("crypto",),
            mode=PortfolioMode.PAPER,
            initial_equity=Decimal("100000"),
            opened_by=refs["PM"],
        )
        company.book.allocate(
            session,
            portfolio_ref=book.ref,
            version_ref=version_ref,
            weight=Decimal("0.8"),
            rationale="most of the book",
            decided_by=refs["PM"],
        )
        with pytest.raises(IntegrityViolation, match="claiming leverage nobody decided"):
            company.book.allocate(
                session,
                portfolio_ref=book.ref,
                version_ref=version_ref,
                weight=Decimal("0.5"),
                rationale="and then some",
                decided_by=refs["PM"],
            )


def test_a_portfolio_has_no_live_mode(company: Runtime) -> None:
    """ADR-0006, at the schema level."""
    from aurelis.portfolio.tables import Portfolio

    assert "live" not in {mode.value for mode in PortfolioMode}
    with pytest.raises(Exception, match="ck_portfolio_has_no_live_mode"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO portfolios (portfolio_id, ref, name, desks, mode, "
                "base_currency, initial_equity, constraints, opened_by, created_at) "
                "VALUES (:i,'PTF-9999','x','[]','live','USD','0','{}','AG-0001',"
                "'2026-01-01 00:00:00')"
            ),
            {"i": uuid7().hex},
        )
    assert Portfolio.__tablename__ == "portfolios"


# ----------------------------- acceptance (a): a promoted version is frozen


def test_modifying_a_validated_version_is_refused_by_the_database(
    company: Runtime,
) -> None:
    """M8 acceptance (a), first half. Around the runtime entirely."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _pass_every_gate(company, session, version_ref, refs["VALID"])
        promoted = company.strategies.promote(
            session,
            version_ref=version_ref,
            decided_by_meeting="MTG-0002",
            actor=refs["GOV"],
        )

    assert isinstance(promoted, StrategyVersion)
    assert promoted.promoted_at is not None

    with pytest.raises(Exception, match="promoted strategy version is immutable"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE strategy_versions SET spec_digest = 'tampered' WHERE ref = :r"
            ),
            {"r": version_ref},
        )


def test_a_material_change_becomes_a_new_version_under_review(
    company: Runtime,
) -> None:
    """M8 acceptance (a), second half."""
    with company.database.session() as session:
        refs = _refs(company, session)
        first = _compose(company, session, refs)
        _pass_every_gate(company, session, first, refs["VALID"])
        company.strategies.promote(
            session,
            version_ref=first,
            decided_by_meeting="MTG-0002",
            actor=refs["GOV"],
        )

        original = company.synthesis.components_of(session, first)[0]
        replacement = _signal(
            company,
            session,
            refs["STRAT"],
            name="funding skew, basis-neutralised",
            origin=Origin.REFINED,
            origin_ref=original.ref,
        )
        composition = company.synthesis.mutate(
            session,
            version_ref=first,
            replace=original,
            with_component=replacement,
            author=refs["STRAT"],
            reason="decorrelate from the deployed book",
        )
        second = composition.version
        parent = company.strategies.version(session, first)

    assert second.ref != first
    assert second.n == 2
    assert second.supersedes == first
    assert second.material_change
    assert second.state == StrategyState.UNDER_REVIEW
    assert second.promoted_at is None
    assert parent.spec_digest != second.spec_digest, "the parent is untouched"


def test_a_gate_cannot_be_evaluated_before_it_was_registered(
    company: Runtime,
) -> None:
    """Around the runtime: the trigger, not the service."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        company.gates.register(
            session,
            version_ref=version_ref,
            gate=Gate.A_STATISTICAL,
            metric="deflated_sharpe",
            comparison="gte",
            value=Decimal("0.95"),
            registered_by=refs["VALID"],
        )

    with pytest.raises(Exception, match="cannot be evaluated before"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE promotion_gates SET evaluated_at = '2000-01-01 00:00:00', "
                "passed = 1 WHERE version_ref = :r AND gate = 'A'"
            ),
            {"r": version_ref},
        )


# --------------------------- acceptance (b): Risk cannot be bypassed


def _propose(
    company: Runtime,
    session: sa.orm.Session,
    refs: dict[str, str],
    version_ref: str,
    *,
    desired: Decimal = Decimal("12000"),
) -> TradeProposal:
    book = company.book.open(
        session,
        name="Crypto book",
        desks=("crypto",),
        mode=PortfolioMode.PAPER,
        initial_equity=Decimal("100000"),
        opened_by=refs["PM"],
    )
    proposal = TradeProposal(
        proposal_id=uuid7(),
        ref="TPR-0001",
        portfolio_ref=book.ref,
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
    return proposal


def test_a_proposal_without_an_assessment_cannot_be_approved(
    company: Runtime,
) -> None:
    """M8 acceptance (b), through the service."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _propose(company, session, refs, version_ref)
        with pytest.raises(IntegrityViolation, match="has no risk assessment"):
            company.risk.approve(
                session, proposal_ref="TPR-0001", approver=refs["TRADE"]
            )


def test_the_database_refuses_an_approval_without_an_assessment(
    company: Runtime,
) -> None:
    """M8 acceptance (b), around the runtime entirely."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _propose(company, session, refs, version_ref)

    with pytest.raises(Exception, match="requires a permitting risk assessment"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO trade_approvals (approval_id, ref, proposal_ref, "
                "assessment_ref, final_target, approved_by, approved_at) VALUES "
                "(:i,'TAP-9999','TPR-0001','RSK-9999','1','AG-0001',"
                "'2026-01-01 00:00:00')"
            ),
            {"i": uuid7().hex},
        )


def test_an_approval_may_not_exceed_what_risk_allowed(company: Runtime) -> None:
    """A regression, and the reason the comparison is cast.

    Money is stored as text so it round-trips exactly. SQLite compares an
    integer to a string by type class rather than by value, so the obvious
    ``NEW.final_target > a.allowed_exposure`` was *always false* and silently
    permitted every oversized approval it was written to stop.
    """
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _propose(company, session, refs, version_ref)
        company.risk.set_limit(
            session,
            scope="desk",
            scope_id="crypto",
            metric="exposure",
            bound=Decimal("5000"),
            reason="new desk, unproven in paper",
            set_by=refs["RISK"],
        )
        assessment = company.risk.assess(
            session, proposal_ref="TPR-0001", assessor=refs["RISK"]
        )

    assert assessment.decision == RiskDecision.SHRINK.value

    with pytest.raises(Exception, match="may not exceed the exposure Risk allowed"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO trade_approvals (approval_id, ref, proposal_ref, "
                "assessment_ref, final_target, approved_by, approved_at) VALUES "
                "(:i,'TAP-9998','TPR-0001',:a,12000,'AG-0001',"
                "'2026-01-01 00:00:00')"
            ),
            {"i": uuid7().hex, "a": assessment.ref},
        )


def test_risk_shrinks_and_the_three_numbers_are_all_persisted(
    company: Runtime,
) -> None:
    """"Risk allowed it" and "Risk was never asked" must be different rows."""
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _propose(company, session, refs, version_ref)
        company.risk.set_limit(
            session,
            scope="desk",
            scope_id="crypto",
            metric="exposure",
            bound=Decimal("5000"),
            reason="new desk, unproven in paper",
            set_by=refs["RISK"],
        )
        company.risk.assess(session, proposal_ref="TPR-0001", assessor=refs["RISK"])
        approval = company.risk.approve(
            session, proposal_ref="TPR-0001", approver=refs["TRADE"]
        )
        proposal = session.execute(
            sa.select(TradeProposal).where(TradeProposal.ref == "TPR-0001")
        ).scalar_one()

    assert proposal.desired_exposure == Decimal("12000")
    assert proposal.allowed_exposure == Decimal("5000")
    assert proposal.final_target == Decimal("5000")
    assert approval.final_target == Decimal("5000")


def test_risk_records_a_decision_even_when_it_changes_nothing(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _propose(company, session, refs, version_ref, desired=Decimal("100"))
        assessment = company.risk.assess(
            session, proposal_ref="TPR-0001", assessor=refs["RISK"]
        )
        kinds = {event.kind for event in company.ledger.tail(session, 400)}

    assert assessment.decision == RiskDecision.ALLOW.value
    assert assessment.allowed_exposure == assessment.desired_exposure
    assert "permitted and unexamined are different rows" in assessment.reason
    assert EventKind.RISK_ASSESSED in kinds


def test_a_latched_kill_halts_everything_and_code_cannot_clear_it(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _propose(company, session, refs, version_ref)
        company.risk.latch(
            session,
            scope="desk",
            scope_id="crypto",
            tripwire="drawdown_floor",
            observed="-0.31",
            threshold="-0.25",
            detail="paper drawdown breached the preregistered floor",
        )
        assessment = company.risk.assess(
            session, proposal_ref="TPR-0001", assessor=refs["RISK"]
        )
        with pytest.raises(IntegrityViolation, match="halt"):
            company.risk.approve(
                session, proposal_ref="TPR-0001", approver=refs["TRADE"]
            )

    assert assessment.decision == RiskDecision.HALT.value
    assert assessment.allowed_exposure == 0
    assert "never cleared by code" in assessment.reason
    assert not hasattr(company.risk, "clear_latch")
    assert not hasattr(company.risk, "unlatch")


def test_a_veto_allows_nothing_and_the_database_agrees(company: Runtime) -> None:
    """Written by a risk role, so the CHECK is what refuses it."""
    with company.database.session() as session:
        assessor = _refs(company, session)["RISK"]

    with pytest.raises(Exception, match="ck_veto_allows_nothing"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO risk_assessments (assessment_id, ref, proposal_ref, "
                "assessor, desired_exposure, allowed_exposure, decision, "
                "limits_applied, reason, assessed_at) VALUES "
                "(:i,'RSK-9999','TPR-0001',:a,'100','50','veto','[]','x',"
                "'2026-01-01 00:00:00')"
            ),
            {"i": uuid7().hex, "a": assessor},
        )


# --------------------------------------------------------- lifecycle


def test_a_strategy_cannot_skip_states(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        strategy = company.synthesis.open_strategy(
            session,
            name="Skipper",
            thesis="Straight to paper.",
            desk=Desk.CRYPTO,
            owner=refs["STRAT"],
        )
        with pytest.raises(IntegrityViolation, match="cannot move idea -> paper_trading"):
            company.strategies.transition(
                session,
                strategy_ref=strategy.ref,
                target=StrategyState.PAPER_TRADING,
                reason="in a hurry",
                actor=refs["STRAT"],
            )


def test_degradation_carries_the_measurement_that_fired_it(company: Runtime) -> None:
    """A preregistered rule, not a judgement."""
    with company.database.session() as session:
        refs = _refs(company, session)
        first = _compose(company, session, refs)
        _pass_every_gate(company, session, first, refs["VALID"])
        promoted = company.strategies.promote(
            session,
            version_ref=first,
            decided_by_meeting="MTG-0002",
            actor=refs["GOV"],
        )
        assert isinstance(promoted, StrategyVersion)
        strategy_ref = promoted.strategy_ref

        company.strategies.transition(
            session,
            strategy_ref=strategy_ref,
            target=StrategyState.PAPER_TRADING,
            reason="risk assessed and limits set",
            actor=refs["RISK"],
        )
        degraded = company.strategies.degrade(
            session,
            strategy_ref=strategy_ref,
            tripwire="rolling_sharpe_floor",
            observed="0.11",
            threshold="0.30",
            actor=refs["RISK"],
        )

    assert degraded.state == StrategyState.DEGRADED
    assert "rolling_sharpe_floor fired" in degraded.state_reason
    assert "0.11" in degraded.state_reason


def test_the_whole_layer_is_recorded_in_the_ledger(company: Runtime) -> None:
    with company.database.session() as session:
        refs = _refs(company, session)
        version_ref = _compose(company, session, refs)
        _pass_every_gate(company, session, version_ref, refs["VALID"])
        company.strategies.promote(
            session,
            version_ref=version_ref,
            decided_by_meeting="MTG-0002",
            actor=refs["GOV"],
        )
        kinds = {event.kind for event in company.ledger.tail(session, 500)}

    for kind in (
        EventKind.COMPONENT_AUTHORED,
        EventKind.STRATEGY_OPENED,
        EventKind.STRATEGY_VERSION_COMPOSED,
        EventKind.GATE_REGISTERED,
        EventKind.GATE_EVALUATED,
        EventKind.VERSION_PROMOTED,
    ):
        assert kind in kinds, kind


def test_the_strategy_tables_are_in_the_declared_schema() -> None:
    import aurelis.portfolio.tables as portfolio_tables
    import aurelis.risk.tables as risk_tables
    import aurelis.strategy.tables as strategy_tables
    from aurelis.schema import TABLE_MODULES

    for module in (strategy_tables, portfolio_tables, risk_tables):
        assert module in TABLE_MODULES


def test_the_runtime_exposes_the_new_layers(company: Runtime) -> None:
    assert company.synthesis is not None
    assert company.gates is not None
    assert company.strategies is not None
    assert company.book is not None
    assert company.risk is not None
