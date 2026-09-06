"""Engines, preregistration, and the verdict rule.

The M4 acceptance criteria. The trigger tests go around the runtime entirely
and write raw SQL, because preregistration that only the application enforces
is preregistration an attacker, a migration or a careless code path walks
straight past.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.engines import (
    DataSpec,
    ExperimentSpec,
    LocalEngine,
    Metric,
    MetricSet,
    SignalSpec,
    UniverseSpec,
    UnsupportedMetric,
    available_engines,
    deflated_sharpe,
    engine_for,
    survey,
)
from aurelis.engines.martex import MartexStatistics, martex_version
from aurelis.research.states import (
    ComputedBy,
    EvidenceKind,
    HypothesisState,
    RegistrationKind,
    Verdict,
)
from aurelis.research.tables import Evidence, Finding, Registration, Result, Run
from aurelis.research.triggers import (
    expected_research_trigger_names,
    verify_research_invariants,
)
from aurelis.research.verdict import Criterion, derive_verdict, parse_criteria
from aurelis.runtime import Runtime


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


def _spec(**overrides: object) -> ExperimentSpec:
    base: dict[str, object] = {
        "engine": "local",
        "universe": UniverseSpec(desk="crypto", symbols=("BTC/USDT",)),
        "data": DataSpec(source="fixture", bars=240),
        "signal": SignalSpec(kind="momentum", lookback=12),
        "metrics": ("total_return", "sharpe", "max_drawdown", "n_trades", "cost_drag"),
    }
    base.update(overrides)
    return ExperimentSpec(**base)  # type: ignore[arg-type]


def _metrics(
    value: str, low: str | None = None, high: str | None = None, name: str = "sharpe"
) -> MetricSet:
    return MetricSet(
        (
            Metric(
                name,
                Decimal(value),
                low=Decimal(low) if low is not None else None,
                high=Decimal(high) if high is not None else None,
            ),
        )
    )


# =========================================================== engines


def test_the_same_spec_and_seed_reproduce_an_identical_artifact(company: Runtime) -> None:
    """The M4 acceptance criterion, and the basis of every citation."""
    first = LocalEngine().run(_spec())
    second = LocalEngine().run(_spec())
    assert first.digest() == second.digest()
    assert first.data_fingerprint == second.data_fingerprint


def test_a_different_seed_or_spec_produces_a_different_artifact() -> None:
    baseline = LocalEngine().run(_spec()).digest()
    assert LocalEngine().run(_spec(seed=1)).digest() != baseline
    assert (
        LocalEngine().run(_spec(signal=SignalSpec(kind="momentum", lookback=30))).digest()
        != baseline
    )


def test_the_spec_digest_survives_the_database_round_trip() -> None:
    """A registration's hash must not change simply by being written down."""
    spec = _spec()
    from aurelis.engines.spec import spec_from_payload

    assert spec_from_payload(spec.as_payload()).digest() == spec.digest()


def test_an_engine_refuses_a_signal_it_does_not_implement() -> None:
    """A typed refusal, never a plausible wrong number."""
    with pytest.raises(UnsupportedMetric, match="does not implement signal"):
        engine_for(_spec(signal=SignalSpec(kind="astrology")))


def test_an_engine_refuses_a_desk_it_does_not_cover() -> None:
    with pytest.raises(UnsupportedMetric, match="does not cover the options desk"):
        engine_for(_spec(universe=UniverseSpec(desk="options", symbols=("SPX",))))


def test_an_engine_refuses_a_metric_it_cannot_compute() -> None:
    with pytest.raises(UnsupportedMetric, match="cannot compute"):
        engine_for(_spec(metrics=("sharpe", "greeks")))


def test_costs_are_charged_and_never_zero_by_default() -> None:
    """A backtest without costs is not evidence."""
    artifact = LocalEngine().run(_spec())
    drag = artifact.metrics.get("cost_drag")
    assert drag.value > 0, "an active strategy must pay to trade"


def test_a_strategy_that_never_trades_pays_nothing() -> None:
    artifact = LocalEngine().run(_spec(signal=SignalSpec(kind="never_trade")))
    assert artifact.metrics.get("cost_drag").value == 0
    assert artifact.metrics.get("n_trades").value == 0


def test_the_signal_cannot_act_on_the_bar_it_trades_into() -> None:
    """One-bar latency, which is what makes look-ahead structurally impossible.

    A rule that could see bar t's close and trade at bar t's open would earn
    the intrabar move for free. Shifting the whole series by one bar must
    therefore change the result -- if it did not, the latency is not being
    applied.
    """
    engine = LocalEngine()
    baseline = engine.run(_spec(data=DataSpec(source="fixture", bars=240)))
    shifted = engine.run(_spec(data=DataSpec(source="fixture", bars=239)))
    assert baseline.metrics.get("total_return").value != shifted.metrics.get(
        "total_return"
    ).value


def test_sharpe_carries_an_interval_and_the_method_that_made_it() -> None:
    """A metric that cannot say how it was produced cannot be reproduced."""
    sharpe = LocalEngine().run(_spec()).metrics.get("sharpe")
    assert sharpe.has_interval
    assert sharpe.low < sharpe.value < sharpe.high
    assert sharpe.method


def test_a_short_series_reports_no_interval_rather_than_a_fake_one() -> None:
    artifact = LocalEngine().run(_spec(data=DataSpec(source="fixture", bars=3)))
    assert not artifact.metrics.get("sharpe").has_interval


def test_the_local_engine_is_always_available() -> None:
    assert "local" in available_engines()


def test_every_engine_declares_its_state(company: Runtime) -> None:
    for capabilities in survey():
        assert capabilities.detail, f"{capabilities.name} does not say what state it is in"


# =============================================== deflated Sharpe (martex)


@pytest.mark.skipif(martex_version() is None, reason="martex-quant is not installed")
def test_more_trials_raise_the_bar_a_claim_must_clear() -> None:
    """The mechanism that makes the graveyard load-bearing.

    Every trial the company has ever run raises the Sharpe that luck alone
    would be expected to produce, so a finding drawn from a thousand quiet
    attempts must clear a higher hurdle than one drawn from three.
    """
    few = deflated_sharpe(
        observed_sharpe=1.2, n_observations=500, n_trials=3, trial_sharpe_variance=0.25
    )
    many = deflated_sharpe(
        observed_sharpe=1.2, n_observations=500, n_trials=500, trial_sharpe_variance=0.25
    )
    assert many.benchmark > few.benchmark
    assert many.deflated < few.deflated


@pytest.mark.skipif(martex_version() is None, reason="martex-quant is not installed")
def test_a_mediocre_sharpe_does_not_survive_a_large_corpus() -> None:
    result = deflated_sharpe(
        observed_sharpe=0.12, n_observations=200, n_trials=174, trial_sharpe_variance=0.25
    )
    assert not result.clears_the_bar


@pytest.mark.skipif(martex_version() is None, reason="martex-quant is not installed")
def test_the_deflated_metric_names_the_library_that_computed_it() -> None:
    metric = MartexStatistics.deflate(Decimal("1.2"), n_observations=500, n_trials=10)
    assert "martex.probabilistic_sharpe_ratio" in metric.method
    assert "n_trials=10" in metric.method


def test_a_single_trial_needs_at_least_itself() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        deflated_sharpe(
            observed_sharpe=1.0, n_observations=100, n_trials=0, trial_sharpe_variance=0.25
        )


# ============================================================ the verdict


def _criteria(comparison: str = "gt", value: str = "0", on: str = "low") -> tuple[Criterion, ...]:
    return parse_criteria(
        [{"metric": "sharpe", "comparison": comparison, "value": value, "on": on}]
    )


def test_all_criteria_holding_gives_confirmed() -> None:
    report = derive_verdict(
        _metrics("0.40", "0.30", "0.50"),
        _criteria(),
        minimum_effect=Decimal("0.20"),
        primary_metric="sharpe",
    )
    assert report.verdict is Verdict.CONFIRMED


def test_a_wide_interval_is_underpowered_not_a_confirmation() -> None:
    """Power is tested first, and that ordering is the point.

    The point estimate clears the bar; the interval is far too wide for the
    data to have settled anything. Testing the criteria first would report
    this as a discovery.
    """
    report = derive_verdict(
        _metrics("0.40", "-2.0", "2.8"),
        _criteria(comparison="gt", value="0", on="point"),
        minimum_effect=Decimal("0.05"),
        primary_metric="sharpe",
    )
    assert report.verdict is Verdict.UNDERPOWERED
    assert "could not have detected" in report.reason


def test_a_missing_interval_is_underpowered() -> None:
    report = derive_verdict(
        _metrics("0.40"),
        _criteria(),
        minimum_effect=Decimal("0.05"),
        primary_metric="sharpe",
    )
    assert report.verdict is Verdict.UNDERPOWERED


def test_an_interval_excluding_the_claim_is_refuted() -> None:
    report = derive_verdict(
        _metrics("-0.30", "-0.34", "-0.26"),
        _criteria(),
        minimum_effect=Decimal("0.20"),
        primary_metric="sharpe",
    )
    assert report.verdict is Verdict.REFUTED
    assert "ruled out" in report.reason


def test_failing_the_bar_while_still_containing_it_is_inconclusive() -> None:
    """Not a refutation. The data did not settle the question either way."""
    report = derive_verdict(
        _metrics("0.12", "-0.02", "0.26"),
        _criteria(),
        minimum_effect=Decimal("0.20"),
        primary_metric="sharpe",
    )
    assert report.verdict is Verdict.INCONCLUSIVE
    assert "did not settle" in report.reason


def test_a_missing_primary_metric_is_invalid_not_a_result() -> None:
    report = derive_verdict(
        _metrics("0.4", "0.3", "0.5", name="total_return"),
        _criteria(),
        minimum_effect=Decimal("0.1"),
        primary_metric="sharpe",
    )
    assert report.verdict is Verdict.INVALID


def test_the_verdict_shows_its_arithmetic() -> None:
    report = derive_verdict(
        _metrics("0.40", "0.30", "0.50"),
        _criteria(),
        minimum_effect=Decimal("0.20"),
        primary_metric="sharpe",
    )
    assert any("PASS" in check for check in report.checks)
    assert any("power" in check for check in report.checks)


def test_malformed_criteria_are_refused_not_skipped() -> None:
    """Skipping one would silently drop a condition the registration promised."""
    with pytest.raises(ValueError, match="malformed"):
        parse_criteria([{"metric": "sharpe", "comparison": "vibes", "value": "0"}])
    with pytest.raises(ValueError, match="malformed"):
        parse_criteria([{"metric": "sharpe", "comparison": "gt", "value": "0", "on": "guess"}])


def test_a_registration_must_declare_something_to_fail() -> None:
    with pytest.raises(ValueError, match="at least one pass criterion"):
        parse_criteria([])


# ================================================ preregistration invariants


def _seed_lifecycle(company: Runtime, **register: object) -> dict[str, str]:
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        gov = company.roster.by_handle(session, "GOV").ref
        hypothesis = company.research.propose(
            session,
            claim="Momentum earns a positive Sharpe after costs.",
            author=quant,
            minimum_effect=Decimal("0.05"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
            desk="crypto",
        )
        company.research.screen(session, hypothesis.ref)
        registration = company.research.register(
            session,
            hypothesis_ref=hypothesis.ref,
            spec=_spec(),
            registrar=gov,
            pass_criteria=[
                {"metric": "sharpe", "comparison": "gt", "value": "0", "on": "low"}
            ],
            **register,  # type: ignore[arg-type]
        )
        experiment = company.research.design(
            session, registration_ref=registration.ref, designer=quant
        )
        return {
            "hypothesis": hypothesis.ref,
            "registration": registration.ref,
            "experiment": experiment.ref,
            "quant": quant,
            "gov": gov,
        }


def test_the_research_triggers_are_installed(company: Runtime) -> None:
    with company.database.engine.connect() as connection:
        assert verify_research_invariants(connection) == ()
    assert len(expected_research_trigger_names()) == 3


def test_a_run_without_a_prior_locked_registration_is_refused_by_the_database(
    company: Runtime,
) -> None:
    """The M4 acceptance criterion. Around the runtime entirely."""
    with pytest.raises(Exception, match="requires a registration locked before"), \
            company.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (run_id, ref, experiment_ref, registration_ref, "
                "engine, code_version, data_fingerprint, seed, status, "
                "failure_reason, duration_ms, started_at) VALUES "
                "(:i, 'RUN-9999', 'EXP-9999', 'REG-9999', 'local', 'x', 'y', 0, "
                "'completed', '', 0, '2026-01-01 00:00:00')"
            ),
            {"i": "0" * 32},
        )


def test_a_registration_locked_after_the_run_does_not_count(company: Runtime) -> None:
    """"Exists" is not the property that matters; "locked beforehand" is.

    A registration written after the numbers were seen provides exactly none
    of the protection preregistration exists for.
    """
    refs = _seed_lifecycle(company)
    with pytest.raises(Exception, match="locked before"), \
            company.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (run_id, ref, experiment_ref, registration_ref, "
                "engine, code_version, data_fingerprint, seed, status, "
                "failure_reason, duration_ms, started_at) VALUES "
                "(:i, 'RUN-8888', :e, :r, 'local', 'x', 'y', 0, 'completed', "
                "'', 0, '2020-01-01 00:00:00')"
            ),
            {"i": "1" * 32, "e": refs["experiment"], "r": refs["registration"]},
        )


def test_a_locked_registration_cannot_be_edited_through_raw_sql(
    company: Runtime,
) -> None:
    """This is what stops a disappointing test from being quietly re-aimed."""
    refs = _seed_lifecycle(company)
    for column, value in (
        ("pass_criteria", '[{"metric":"sharpe","comparison":"gt","value":"-99","on":"low"}]'),
        ("spec_digest", "0" * 64),
        ("seed", "42"),
        ("kind", "'exploratory'"),
    ):
        with pytest.raises(Exception, match="locked registration is immutable"), \
                company.database.engine.begin() as conn:
            literal = value if column == "seed" else f"'{value}'" if column != "kind" else value
            conn.execute(
                sa.text(
                    f"UPDATE registrations SET {column} = {literal} WHERE ref = :r"  # noqa: S608
                ),
                {"r": refs["registration"]},
            )


def test_an_unlocked_registration_may_still_be_edited(company: Runtime) -> None:
    """Otherwise the immutability test proves nothing about locking."""
    refs = _seed_lifecycle(company)
    with company.database.engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE registrations SET locked_at = NULL WHERE ref = :r"),
            {"r": refs["registration"]},
        )
        conn.execute(
            sa.text("UPDATE registrations SET seed = 7 WHERE ref = :r"),
            {"r": refs["registration"]},
        )


def test_a_result_requires_a_completed_run(company: Runtime) -> None:
    with pytest.raises(Exception, match="requires a completed run"), \
            company.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO results (result_id, run_ref, metric, value, unit, "
                "method, split, computed_by, artifact_digest, created_at) VALUES "
                "(:i, 'RUN-7777', 'sharpe', '9.9', '', '', 'train', 'engine', "
                "'d', '2026-01-01 00:00:00')"
            ),
            {"i": "2" * 32},
        )


def test_no_agent_can_write_a_result(company: Runtime) -> None:
    """The M4 acceptance criterion, enforced by a CHECK constraint.

    ``computed_by`` accepts only ``engine`` or ``custodian``. There is no
    value an agent could put there, so there is no path by which an opinion
    becomes a measurement.
    """
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, _ = company.research.execute(session, experiment_ref=refs["experiment"])
        run_ref = run.ref

    with pytest.raises(Exception, match="ck_result_computed_by_machine_only"), \
            company.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO results (result_id, run_ref, metric, value, unit, "
                "method, split, computed_by, artifact_digest, created_at) VALUES "
                "(:i, :r, 'fabricated', '9.9', '', '', 'train', :a, 'd', "
                "'2026-01-01 00:00:00')"
            ),
            {"i": "3" * 32, "r": run_ref, "a": refs["quant"]},
        )


def test_a_sealed_result_can_only_come_from_the_custodian(company: Runtime) -> None:
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, _ = company.research.execute(session, experiment_ref=refs["experiment"])
        run_ref = run.ref

    with pytest.raises(Exception, match="ck_sealed_results_come_from_the_custodian"), \
            company.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO results (result_id, run_ref, metric, value, unit, "
                "method, split, computed_by, artifact_digest, created_at) VALUES "
                "(:i, :r, 'sharpe', '9.9', '', '', 'sealed', 'engine', 'd', "
                "'2026-01-01 00:00:00')"
            ),
            {"i": "4" * 32, "r": run_ref},
        )


def test_runs_and_results_are_append_only(company: Runtime) -> None:
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        company.research.execute(session, experiment_ref=refs["experiment"])

    for table, column in (("runs", "started_at"), ("results", "created_at")):
        with pytest.raises(Exception, match="append-only"), \
                company.database.engine.begin() as conn:
            conn.execute(sa.text(f"UPDATE {table} SET {column} = {column}"))  # noqa: S608


def test_only_the_registrar_may_lock_a_registration() -> None:
    from aurelis.org import CHARTERS
    from aurelis.org.scopes import WriteScope

    holders = [
        cid for cid, c in CHARTERS.items() if WriteScope.REGISTRATION in c.write_scopes
    ]
    assert holders == ["gov.registrar"]


# ============================================================== lifecycle


def test_a_hypothesis_runs_all_the_way_to_a_verdict(company: Runtime) -> None:
    """The M4 acceptance criterion: draft to verdict, every number traceable."""
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, artifact = company.research.execute(session, experiment_ref=refs["experiment"])
        outcome = company.research.conclude(
            session,
            run_ref=run.ref,
            artifact=artifact,
            author=refs["quant"],
            interpretation="Costs dominate the signal on this window.",
        )

    assert outcome.verdict in {
        Verdict.CONFIRMED,
        Verdict.REFUTED,
        Verdict.INCONCLUSIVE,
        Verdict.UNDERPOWERED,
    }
    assert outcome.report.checks


def test_every_result_names_the_artifact_it_came_from(company: Runtime) -> None:
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, _ = company.research.execute(session, experiment_ref=refs["experiment"])
        results = session.execute(
            sa.select(Result).where(Result.run_ref == run.ref)
        ).scalars().all()

    assert results
    for result in results:
        assert result.computed_by == ComputedBy.ENGINE
        assert result.artifact_digest
        assert company.artifacts.exists(result.artifact_digest)


def test_the_run_records_its_full_provenance(company: Runtime) -> None:
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, _ = company.research.execute(session, experiment_ref=refs["experiment"])
    assert run.code_version
    assert run.data_fingerprint
    assert run.artifact_digest


def test_the_finding_carries_the_arithmetic_behind_its_verdict(company: Runtime) -> None:
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, artifact = company.research.execute(session, experiment_ref=refs["experiment"])
        company.research.conclude(
            session,
            run_ref=run.ref,
            artifact=artifact,
            author=refs["quant"],
            interpretation="No edge here.",
        )
        finding = session.execute(sa.select(Finding)).scalars().one()
    assert finding.verdict_checks
    assert finding.verdict_reason


def test_the_observed_fact_evidence_names_an_artifact(company: Runtime) -> None:
    """The assertion ladder: an observed fact must point at a measurement."""
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, artifact = company.research.execute(session, experiment_ref=refs["experiment"])
        company.research.conclude(
            session,
            run_ref=run.ref,
            artifact=artifact,
            author=refs["quant"],
            interpretation="No edge here.",
        )
        evidence = session.execute(sa.select(Evidence)).scalars().one()
    assert evidence.kind == EvidenceKind.OBSERVED_FACT
    assert evidence.artifact_digest


def test_an_observed_fact_without_an_artifact_is_refused(company: Runtime) -> None:
    with pytest.raises(Exception, match="ck_observed_fact_names_its_artifact"), \
            company.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO evidence (evidence_id, finding_ref, kind, polarity, "
                "statement, verbatim, author, created_at) VALUES "
                "(:i, 'FND-9999', 'observed_fact', 'supports', 'trust me', '', "
                "'AG-0006', '2026-01-01 00:00:00')"
            ),
            {"i": "5" * 32},
        )


def test_a_hypothesis_needs_a_positive_minimum_effect(company: Runtime) -> None:
    """A zero minimum effect makes every result significant."""
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        with pytest.raises(IntegrityViolation, match="minimum_effect must be positive"):
            company.research.propose(
                session,
                claim="Anything at all.",
                author=quant,
                minimum_effect=Decimal("0"),
                primary_metric="sharpe",
                family="strategy.x",
            )


def test_a_revised_registration_is_degraded_to_exploratory(company: Runtime) -> None:
    """A disappointing confirmatory test cannot be quietly re-aimed."""
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        revised = company.research.register(
            session,
            hypothesis_ref=refs["hypothesis"],
            spec=_spec(signal=SignalSpec(kind="momentum", lookback=30)),
            registrar=refs["gov"],
            pass_criteria=[
                {"metric": "sharpe", "comparison": "gt", "value": "0", "on": "low"}
            ],
            kind=RegistrationKind.CONFIRMATORY,
            supersedes=refs["registration"],
        )
    assert revised.kind == RegistrationKind.EXPLORATORY
    assert "degraded" in revised.degraded_reason


def test_nothing_may_be_designed_from_an_unlocked_registration(company: Runtime) -> None:
    refs = _seed_lifecycle(company)
    with company.database.engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE registrations SET locked_at = NULL WHERE ref = :r"),
            {"r": refs["registration"]},
        )
    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(IntegrityViolation, match="is not locked"):
            company.research.design(
                session, registration_ref=refs["registration"], designer=refs["quant"]
            )


def test_declared_cells_count_what_was_declared_not_what_ran(company: Runtime) -> None:
    """The declare-big-run-small loophole, closed."""
    _seed_lifecycle(company, declared_cells=200)
    with company.database.session() as session:
        assert company.research.trial_count(session, "strategy.momentum") == 200


def test_the_trial_count_owns_its_subtree(company: Runtime) -> None:
    _seed_lifecycle(company, declared_cells=8)
    with company.database.session() as session:
        assert company.research.trial_count(session, "strategy") == 8
        assert company.research.trial_count(session, "strategy.momentum.crypto") == 8
        assert company.research.trial_count(session, "portfolio") == 0


def test_a_settled_hypothesis_appears_in_the_graveyard(company: Runtime) -> None:
    """Killed research is kept and queryable, not quietly dropped."""
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, artifact = company.research.execute(session, experiment_ref=refs["experiment"])
        outcome = company.research.conclude(
            session,
            run_ref=run.ref,
            artifact=artifact,
            author=refs["quant"],
            interpretation="No edge.",
        )
        graveyard = company.research.graveyard(session)

    assert outcome.verdict is not Verdict.CONFIRMED
    assert [h.ref for h in graveyard] == [refs["hypothesis"]]
    assert graveyard[0].verdict_reason


def test_a_shelved_duplicate_never_reaches_a_registration(company: Runtime) -> None:
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        hypothesis = company.research.propose(
            session,
            claim="Something already tried.",
            author=quant,
            minimum_effect=Decimal("0.1"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
        )
        company.research.screen(
            session, hypothesis.ref, prior_art=("HYP-0001",), shelve=True
        )
        settled = company.research.hypothesis(session, hypothesis.ref)
    assert settled.state == HypothesisState.SHELVED
    assert settled.prior_art == ["HYP-0001"]


def test_the_lifecycle_is_recorded_end_to_end(company: Runtime) -> None:
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        run, artifact = company.research.execute(session, experiment_ref=refs["experiment"])
        company.research.conclude(
            session,
            run_ref=run.ref,
            artifact=artifact,
            author=refs["quant"],
            interpretation="No edge.",
        )
        kinds = {e.kind for e in company.ledger.tail(session, 300)}
        assert company.ledger.verify(session).ok

    assert EventKind.HYPOTHESIS_PROPOSED.value in kinds
    assert EventKind.REGISTRATION_LOCKED.value in kinds
    assert EventKind.RUN_COMPLETED.value in kinds
    assert EventKind.VERDICT_DERIVED.value in kinds


def test_an_engine_failure_is_recorded_as_a_run_not_swallowed(company: Runtime) -> None:
    """A scientific failure is a research object, never a retry."""
    refs = _seed_lifecycle(company)
    with company.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE experiments SET spec = json_set(spec, '$.signal.kind', "
                "'astrology') WHERE ref = :r"
            ),
            {"r": refs["experiment"]},
        )

    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(UnsupportedMetric):
            company.research.execute(session, experiment_ref=refs["experiment"])

    with company.database.session() as session:
        failed = session.execute(sa.select(Run)).scalars().all()
    assert any(r.status == "scientific_failure" for r in failed)


def test_the_registration_is_stored_as_an_artifact(company: Runtime) -> None:
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        registration = session.execute(
            sa.select(Registration).where(Registration.ref == refs["registration"])
        ).scalar_one()
    assert registration.artifact_digest
    assert company.artifacts.exists(registration.artifact_digest)


def test_the_run_uses_the_spec_that_was_locked(company: Runtime) -> None:
    """An experiment built from anything else would make the lock decorative."""
    refs = _seed_lifecycle(company)
    with company.database.session() as session:
        registration = session.execute(
            sa.select(Registration).where(Registration.ref == refs["registration"])
        ).scalar_one()
        _, artifact = company.research.execute(session, experiment_ref=refs["experiment"])
    assert artifact.spec_digest == registration.spec_digest
