"""Survivorship, the market taxonomy, and the review that kills a confirmed claim.

The M5 acceptance criteria. The centrepiece is
:func:`test_a_confirmed_claim_is_overturned_by_its_own_review`, which runs the
whole demonstration end to end with nobody intervening.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from aurelis.engines import DataSpec, ExperimentSpec, LocalEngine, SignalSpec, UniverseSpec
from aurelis.engines.universe import resolve_universe
from aurelis.intel.sources import FixtureSource
from aurelis.meetings.taxonomy import MARKET_DEFECTS, build_test, defects_for
from aurelis.meetings.types import ObjectionSeverity, ObjectionStatus, ObjectionType
from aurelis.org.scopes import ToolScope
from aurelis.research.review import hold_research_review, survivorship_claim
from aurelis.research.states import Verdict
from aurelis.runtime import Runtime

ANCHOR = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


def _spec(point_in_time: bool, bars: int = 200) -> ExperimentSpec:
    return ExperimentSpec(
        engine="local",
        universe=UniverseSpec(
            desk="crypto",
            symbols=(),
            point_in_time=point_in_time,
            selection="point_in_time" if point_in_time else "survivors_only",
        ),
        data=DataSpec(source="fixture", bars=bars),
        signal=SignalSpec(kind="rotation", lookback=12, parameters={"top_k": 1}),
        metrics=("total_return", "sharpe", "max_drawdown", "n_trades", "cost_drag"),
    )


# ======================================================= the universe


def test_the_fixture_has_instruments_that_actually_died() -> None:
    """Without casualties, survivorship bias is undetectable here."""
    source = FixtureSource()
    assert source.DELISTED
    assert set(source.surviving()).isdisjoint(source.DELISTED)
    for symbol in source.DELISTED:
        assert source.delisted_at(symbol) is not None


def test_the_dying_names_outperform_before_they_collapse() -> None:
    """The reason survivorship bias is dangerous rather than merely untidy.

    LUNA and FTT both looked like the best names right up until they were
    worth nothing. If the casualties here merely drifted down, no ranking
    rule would ever hold one and the bias would not be measurable at all --
    which is exactly what the first version of this fixture got wrong.
    """
    source = FixtureSource()
    for symbol in source.DELISTED:
        bars = source.bars(symbol, limit=200)
        peak = max(bar.close for bar in bars)
        assert peak > bars[0].close * Decimal("1.5"), f"{symbol} never looked good"
        # What matters is the collapse FROM THE PEAK, not from the start. A
        # name can triple and then lose sixty per cent and still finish above
        # where it began -- and the holder who rotated in near the top is
        # still destroyed, which is the cost survivorship bias hides.
        assert bars[-1].close < peak * Decimal("0.5"), f"{symbol} did not collapse"


def test_hindsight_and_point_in_time_are_different_lists() -> None:
    hindsight = resolve_universe("crypto", (), point_in_time=False, as_of=ANCHOR)
    pit = resolve_universe("crypto", (), point_in_time=True, as_of=ANCHOR)
    assert len(pit.symbols) > len(hindsight.symbols)
    assert hindsight.survivorship_exposed
    assert not pit.survivorship_exposed


def test_the_hindsight_universe_reports_what_it_dropped() -> None:
    """A Data Auditor has to be able to ask which names were removed."""
    hindsight = resolve_universe("crypto", (), point_in_time=False, as_of=ANCHOR)
    assert hindsight.excluded
    assert "excluded" in hindsight.describe()


def test_an_explicit_symbol_list_is_honoured_as_given() -> None:
    """A caller that named its instruments already made the selection.

    Quietly widening it would answer a different question than the spec asked.
    """
    resolved = resolve_universe(
        "crypto", ("BTC/USDT",), point_in_time=True, as_of=ANCHOR
    )
    assert resolved.symbols == ("BTC/USDT",)


# ======================================================= the measurement


def test_survivorship_changes_the_result_measurably(company: Runtime) -> None:
    """The whole demonstration rests on this being a measurement."""
    engine = LocalEngine()
    hindsight = engine.run(_spec(point_in_time=False))
    pit = engine.run(_spec(point_in_time=True))

    assert hindsight.diagnostics["survivorship_exposed"] is True
    assert pit.diagnostics["survivorship_exposed"] is False
    assert len(pit.diagnostics["universe"]) > len(hindsight.diagnostics["universe"])

    assert pit.metrics.get("max_drawdown").value > hindsight.metrics.get(
        "max_drawdown"
    ).value


def test_the_bias_is_worth_more_than_a_rounding_error(company: Runtime) -> None:
    engine = LocalEngine()
    hindsight = engine.run(_spec(point_in_time=False)).metrics.get("max_drawdown").value
    pit = engine.run(_spec(point_in_time=True)).metrics.get("max_drawdown").value
    assert pit > hindsight * Decimal("2"), "the defect must be large enough to matter"


def test_path_metrics_carry_a_bootstrap_interval() -> None:
    """Without one they cannot support a confirmatory claim at all."""
    artifact = LocalEngine().run(_spec(point_in_time=False))
    for name in ("max_drawdown", "total_return"):
        metric = artifact.metrics.get(name)
        assert metric.has_interval, f"{name} has no interval"
        assert "bootstrap" in metric.method


def test_the_bootstrap_is_deterministic() -> None:
    """Same spec and seed, same interval -- or the artifact is not citable."""
    first = LocalEngine().run(_spec(point_in_time=False))
    second = LocalEngine().run(_spec(point_in_time=False))
    assert first.digest() == second.digest()


def test_the_drawdown_interval_is_honestly_wide() -> None:
    """A 200-bar drawdown genuinely cannot be pinned to a few points.

    Recorded as a test because it is the reason the demonstration declares a
    minimum effect of 0.11: a claim pretending to resolve 0.05 would be
    UNDERPOWERED, and the verdict rule would be right to say so.
    """
    metric = LocalEngine().run(_spec(point_in_time=False)).metrics.get("max_drawdown")
    assert metric.width > Decimal("0.10")


# ======================================================= the taxonomy


def test_every_market_defect_has_a_mechanical_test() -> None:
    """A Critic names a defect; it does not compose the test."""
    spec = _spec(point_in_time=False)
    for defect_type in MARKET_DEFECTS:
        test = build_test(
            defect_type, spec, metric="max_drawdown", observed=Decimal("0.12")
        )
        assert test["tool"] == ToolScope.ENGINE_BACKTEST.value
        assert test["field"] == "max_drawdown"
        assert test["describes"]


def test_each_builder_varies_exactly_one_thing() -> None:
    """A test that changed two things at once would settle nothing."""
    from aurelis.research.lifecycle import _spec_from_payload

    spec = _spec(point_in_time=False)
    base = spec.as_payload()
    for defect_type in MARKET_DEFECTS:
        test = build_test(
            defect_type, spec, metric="sharpe", observed=Decimal("0.1")
        )
        varied = _spec_from_payload(test["arguments"]["spec"]).as_payload()
        differing = [
            key for key in base if base[key] != varied[key]
        ]
        assert len(differing) == 1, f"{defect_type} varied {differing}"


def test_the_direction_of_worse_depends_on_the_metric() -> None:
    """Drawdown getting bigger is bad; return getting bigger is not.

    Getting this backwards would make every objection unfalsifiable in one
    direction and automatic in the other.
    """
    spec = _spec(point_in_time=False)
    drawdown = build_test(
        ObjectionType.COST_UNDERSTATED, spec, metric="max_drawdown", observed=Decimal("0.1")
    )
    returns = build_test(
        ObjectionType.COST_UNDERSTATED, spec, metric="total_return", observed=Decimal("0.1")
    )
    assert drawdown["comparison"] == "gt"
    assert returns["comparison"] == "lt"


def test_survivorship_is_critical() -> None:
    assert MARKET_DEFECTS[ObjectionType.SURVIVORSHIP].severity is ObjectionSeverity.CRITICAL


def test_inapplicable_defects_are_not_offered() -> None:
    """Noise in a review is what stops real objections being read."""
    already_pit = defects_for(_spec(point_in_time=True))
    assert ObjectionType.SURVIVORSHIP not in {d.type for d in already_pit}

    single_name = ExperimentSpec(
        engine="local",
        universe=UniverseSpec(desk="crypto", symbols=("BTC/USDT",)),
        data=DataSpec(source="fixture", bars=100),
        signal=SignalSpec(kind="momentum", lookback=12),
    )
    assert ObjectionType.CAPACITY_IGNORED not in {
        d.type for d in defects_for(single_name)
    }


def test_a_defect_without_a_builder_is_refused() -> None:
    with pytest.raises(KeyError, match="closed taxonomy"):
        build_test(
            ObjectionType.CROWDING,
            _spec(point_in_time=False),
            metric="sharpe",
            observed=Decimal("0.1"),
        )


# ======================================================= the tools


def test_the_backtest_tool_returns_flat_scalars(company: Runtime) -> None:
    """So a test can name a field without knowing the artifact format."""
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT")
        result = company.tools.invoke(
            session,
            agent_ref=quant.ref,
            scope=ToolScope.ENGINE_BACKTEST,
            arguments={"spec": _spec(point_in_time=True).as_payload()},
            permitted=quant.authority.tools,
        )
    assert "max_drawdown" in result.value
    assert result.value["universe_basis"] == "point_in_time"
    assert int(result.value["universe_size"]) == 6


def test_the_point_in_time_tool_reports_exposure(company: Runtime) -> None:
    with company.database.session() as session:
        auditor = company.roster.by_handle(session, "AUDIT")
        result = company.tools.invoke(
            session,
            agent_ref=auditor.ref,
            scope=ToolScope.INTEGRITY_POINT_IN_TIME,
            arguments={"desk": "crypto", "point_in_time": False},
            permitted=auditor.authority.tools,
        )
    assert result.value["survivorship_exposed"] == "True"
    assert int(result.value["excluded_count"]) == 3


def test_an_analyst_cannot_run_a_backtest(company: Runtime) -> None:
    """Producing evidence for a strategy claim is not an analyst's job."""
    from aurelis.core.errors import PermissionDenied

    with company.database.session() as session:
        intel = company.roster.by_handle(session, "INTEL")
        assert ToolScope.ENGINE_BACKTEST not in intel.authority.tools
        with pytest.raises(PermissionDenied):
            company.tools.invoke(
                session,
                agent_ref=intel.ref,
                scope=ToolScope.ENGINE_BACKTEST,
                arguments={"spec": _spec(True).as_payload()},
                permitted=intel.authority.tools,
            )


# ============================================ the demonstration


def _review(company: Runtime, bars: int = 200):
    with company.database.session() as session:
        return hold_research_review(
            session,
            research=company.research,
            chair=company.chair,
            author=company.roster.by_handle(session, "QUANT").ref,
            critic=company.roster.by_handle(session, "CRITIC").ref,
            chair_ref=company.roster.by_handle(session, "OPS").ref,
            participants=(
                company.roster.by_handle(session, "QUANT").ref,
                company.roster.by_handle(session, "CRITIC").ref,
                company.roster.by_handle(session, "LEAD-R").ref,
            ),
            registrar=company.roster.by_handle(session, "GOV").ref,
            bars=bars,
        )


def test_a_confirmed_claim_is_overturned_by_its_own_review(company: Runtime) -> None:
    """The M5 target demonstration, with no human in the loop.

    A researcher registers a claim, runs it, and it is CONFIRMED. A Critic
    names SURVIVORSHIP. The Chair dispatches the generated test. The
    point-in-time re-run comes back far worse. The objection is upheld and the
    hypothesis is REFUTED -- by a measurement, not by an argument.
    """
    outcome = _review(company)

    assert outcome.verdict_before is Verdict.CONFIRMED, (
        "the review must overturn something the company had actually accepted"
    )
    assert outcome.objection_status is ObjectionStatus.UPHELD
    assert outcome.verdict_after is Verdict.REFUTED
    assert outcome.overturned


def test_the_review_was_settled_by_a_measurement(company: Runtime) -> None:
    outcome = _review(company)
    assert outcome.measured > outcome.claimed
    assert "measured max_drawdown" in outcome.detail
    assert outcome.universe_after > outcome.universe_before
    assert len(outcome.excluded) == 3


def test_the_critic_did_not_write_the_test(company: Runtime) -> None:
    """The prose is the critic's; the arithmetic is not.

    The dispatched test must be exactly what the taxonomy generates for this
    specification -- not something the critic composed, which could have been
    aimed anywhere.
    """
    from aurelis.meetings.tables import MeetingObjection

    outcome = _review(company)
    expected = build_test(
        ObjectionType.SURVIVORSHIP,
        survivorship_claim(200),
        metric="max_drawdown",
        observed=outcome.claimed,
    )
    with company.database.session() as session:
        objection = session.get_one(
            MeetingObjection,
            session.query(MeetingObjection)
            .filter(MeetingObjection.ref == outcome.objection_ref)
            .one()
            .objection_id,
        )
    assert objection.discriminating_test == expected


def test_the_overturning_is_recorded_as_its_own_event(company: Runtime) -> None:
    """A corpus that quietly rewrote conclusions would be worse than one that
    never revised them."""
    from aurelis.core.enums import EventKind

    outcome = _review(company)
    with company.database.session() as session:
        kinds = [
            event.kind
            for event in company.ledger.for_subject(session, outcome.hypothesis_ref)
        ]
    assert EventKind.VERDICT_OVERTURNED.value in kinds


def test_the_refuted_claim_lands_in_the_graveyard(company: Runtime) -> None:
    outcome = _review(company)
    with company.database.session() as session:
        dead = company.research.graveyard(session)
    assert outcome.hypothesis_ref in {h.ref for h in dead}
    entry = next(h for h in dead if h.ref == outcome.hypothesis_ref)
    assert "Survivorship" in entry.verdict_reason
    assert outcome.meeting_ref in entry.verdict_reason


def test_the_critical_objection_blocks_the_meetings_decision(company: Runtime) -> None:
    from aurelis.meetings.tables import Decision

    outcome = _review(company)
    with company.database.session() as session:
        decision = (
            session.query(Decision)
            .filter(Decision.meeting_ref == outcome.meeting_ref)
            .one()
        )
    assert decision.outcome.startswith("BLOCKED")
    assert outcome.objection_ref in decision.evidence_refs


def test_the_whole_review_leaves_a_verifiable_ledger(company: Runtime) -> None:
    _review(company)
    with company.database.session() as session:
        assert company.ledger.verify(session).ok


def test_the_review_is_reproducible(company: Runtime, runtime: Runtime) -> None:
    """Two runs of the demonstration reach the same numbers."""
    first = _review(company)
    second = _review(company)
    assert first.claimed == second.claimed
    assert first.measured == second.measured
    assert first.verdict_after is second.verdict_after
