"""M6: institutional memory.

Three acceptance criteria, and a test named after each:

* a Brainstorm's evidence pack automatically contains "we tried this before",
* ledger reconciliation reproduces the corpus's own claimed totals,
* a finding's confidence degrades when an objection opens against it.

The rest of the file defends the mechanisms those three depend on — chiefly
that independent support is not a count of supporters, and that the vault is a
rendering nobody can write back through.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import uuid7
from aurelis.meetings.tables import MeetingObjection
from aurelis.meetings.types import ObjectionSeverity, ObjectionStatus, ObjectionType
from aurelis.memory.brainstorm import evidence_pack, hold_brainstorm
from aurelis.memory.confidence import ConfidenceBand, assess, write_cap_reason
from aurelis.memory.corpus import (
    MARTEX_CORPUS,
    CorpusNotAvailable,
    find_martex_bundle,
    import_martex_corpus,
)
from aurelis.memory.graph import EdgeKind, KnowledgeGraph, NodeKind
from aurelis.memory.lessons import Lessons
from aurelis.memory.mirror import mirror_research
from aurelis.memory.priorart import family_distance, search, tokenise
from aurelis.memory.tables import CorpusReconciliation, CorpusTrial, KnowledgeEdge
from aurelis.memory.vault import export_vault
from aurelis.research.states import EvidenceKind, Polarity, Verdict
from aurelis.research.tables import Evidence, Finding
from aurelis.runtime import Runtime

# The corpus ships inside the martex-quant wheel. When it is not installed the
# import tests skip rather than fabricate a fixture that claims to be it --
# a stand-in corpus would prove the parser works and nothing about whether
# Aurelis can read the real research record.
try:
    _BUNDLE: Path | None = find_martex_bundle()
except CorpusNotAvailable:
    _BUNDLE = None

needs_corpus = pytest.mark.skipif(
    _BUNDLE is None, reason="martex-quant is not installed; there is no corpus to import"
)


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


# --------------------------------------------------------------------- graph


def _nodes(company: Runtime, session: sa.orm.Session, *refs: str) -> None:
    for ref in refs:
        company.graph.add_node(
            session, node_id=ref, kind=NodeKind.FINDING, label=f"finding {ref}"
        )


def test_an_edge_cannot_point_at_a_node_that_does_not_exist(company: Runtime) -> None:
    with company.database.session() as session:
        _nodes(company, session, "FND-0001")
        with pytest.raises(IntegrityViolation, match="no such node"):
            company.graph.relate(
                session,
                source="FND-0001",
                target="FND-9999",
                kind=EdgeKind.SUPPORTS,
                created_by="AG-0001",
            )


def test_a_correlation_edge_must_state_its_weight(company: Runtime) -> None:
    """An unweighted correlation asserts dependence without saying how much."""
    with company.database.session() as session:
        _nodes(company, session, "FND-0001", "FND-0002")
        with pytest.raises(IntegrityViolation, match="must state its weight"):
            company.graph.relate(
                session,
                source="FND-0001",
                target="FND-0002",
                kind=EdgeKind.CORRELATED_WITH,
                created_by="AG-0001",
            )


def test_the_database_refuses_an_unweighted_correlation_edge(company: Runtime) -> None:
    """The same rule, around the runtime entirely."""
    with company.database.session() as session:
        _nodes(company, session, "FND-0001", "FND-0002")
    with pytest.raises(Exception, match="ck_correlation_states_its_weight"), \
            company.database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO knowledge_edges (edge_id, source, target, kind, "
                "note, created_by, created_at) VALUES "
                "(:i, 'FND-0001', 'FND-0002', 'correlated_with', '', 'x', "
                "'2026-01-01 00:00:00')"
            ),
            {"i": uuid7().hex},
        )


def test_support_is_counted_not_assumed(company: Runtime) -> None:
    """Three independent supporters count as three."""
    with company.database.session() as session:
        _nodes(company, session, "HYP-0001", "FND-0001", "FND-0002", "FND-0003")
        for ref in ("FND-0001", "FND-0002", "FND-0003"):
            company.graph.relate(
                session,
                source=ref,
                target="HYP-0001",
                kind=EdgeKind.SUPPORTS,
                created_by="AG-0001",
            )
        support = company.graph.independent_support(session, "HYP-0001")

    assert support.naive == 3
    assert support.independent == 3
    assert support.overcounted_by == 0
    assert support.discounted == ()


def test_correlated_support_collapses_and_says_so(company: Runtime) -> None:
    """The failure martex-quant made twice: one event, counted as two.

    H59 produced two cells that looked like independent confirmation and
    correlated at 0.821. The discount is applied AND reported -- a number that
    quietly shrank would be indistinguishable from weak support.
    """
    with company.database.session() as session:
        _nodes(company, session, "HYP-0001", "FND-0001", "FND-0002", "FND-0003")
        for ref in ("FND-0001", "FND-0002", "FND-0003"):
            company.graph.relate(
                session,
                source=ref,
                target="HYP-0001",
                kind=EdgeKind.SUPPORTS,
                created_by="AG-0001",
            )
        company.graph.relate(
            session,
            source="FND-0001",
            target="FND-0002",
            kind=EdgeKind.CORRELATED_WITH,
            weight=Decimal("0.821"),
            created_by="AG-0002",
            note="the same underlying event, observed twice",
        )
        support = company.graph.independent_support(session, "HYP-0001")

    assert support.naive == 3
    assert support.independent == 2
    assert support.overcounted_by == 1
    assert support.discounted == (("FND-0001", "FND-0002", Decimal("0.821")),)
    assert "0.821" in support.describe()
    assert "discounted" in support.describe()


def test_correlation_below_the_threshold_does_not_collapse(company: Runtime) -> None:
    with company.database.session() as session:
        _nodes(company, session, "HYP-0001", "FND-0001", "FND-0002")
        for ref in ("FND-0001", "FND-0002"):
            company.graph.relate(
                session,
                source=ref,
                target="HYP-0001",
                kind=EdgeKind.SUPPORTS,
                created_by="AG-0001",
            )
        company.graph.relate(
            session,
            source="FND-0001",
            target="FND-0002",
            kind=EdgeKind.CORRELATED_WITH,
            weight=Decimal("0.35"),
            created_by="AG-0002",
        )
        support = company.graph.independent_support(session, "HYP-0001")

    assert support.independent == 2
    assert support.discounted == ()


def test_correlation_collapses_transitively(company: Runtime) -> None:
    """A correlates with B, B with C: all three are one observation."""
    with company.database.session() as session:
        _nodes(company, session, "HYP-0001", "FND-0001", "FND-0002", "FND-0003")
        for ref in ("FND-0001", "FND-0002", "FND-0003"):
            company.graph.relate(
                session,
                source=ref,
                target="HYP-0001",
                kind=EdgeKind.SUPPORTS,
                created_by="AG-0001",
            )
        for left, right in (("FND-0001", "FND-0002"), ("FND-0002", "FND-0003")):
            company.graph.relate(
                session,
                source=left,
                target=right,
                kind=EdgeKind.CORRELATED_WITH,
                weight=Decimal("0.9"),
                created_by="AG-0002",
            )
        support = company.graph.independent_support(session, "HYP-0001")

    assert support.independent == 1
    assert len(support.discounted) == 2


def test_the_graph_answers_what_breaks_if_this_is_wrong(company: Runtime) -> None:
    with company.database.session() as session:
        _nodes(company, session, "FND-0001", "FND-0002", "FND-0003")
        company.graph.relate(
            session,
            source="FND-0002",
            target="FND-0001",
            kind=EdgeKind.DEPENDS_ON,
            created_by="AG-0001",
        )
        company.graph.relate(
            session,
            source="FND-0003",
            target="FND-0002",
            kind=EdgeKind.DEPENDS_ON,
            created_by="AG-0001",
        )
        blast_radius = company.graph.descendants(session, "FND-0001")
        rests_on = company.graph.ancestors(session, "FND-0003")

    assert blast_radius == ["FND-0002", "FND-0003"]
    assert rests_on == ["FND-0002", "FND-0001"]


def test_relating_the_same_pair_twice_is_idempotent(company: Runtime) -> None:
    with company.database.session() as session:
        _nodes(company, session, "FND-0001", "FND-0002")
        for _ in range(3):
            company.graph.relate(
                session,
                source="FND-0001",
                target="FND-0002",
                kind=EdgeKind.SUPPORTS,
                created_by="AG-0001",
            )
        edges = session.execute(sa.select(sa.func.count()).select_from(KnowledgeEdge))
    assert edges.scalar_one() == 1


# ---------------------------------------------------------------- prior art


def test_prior_art_distinguishes_an_empty_index_from_a_novel_idea(
    company: Runtime,
) -> None:
    """"We found nothing" is only informative if there was something to find."""
    with company.database.session() as session:
        report = search(
            session, claim="Funding extremes predict returns.", family="info.derivatives"
        )
    assert report.searched == 0
    assert report.matches == ()
    assert "novelty is unknown" in report.describe()


def test_prior_art_matches_on_family_even_when_the_words_differ(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        session.add(
            CorpusTrial(
                trial_id=uuid7(),
                corpus="fixture",
                ref="MQ-H08",
                hypothesis="H08",
                family="info.derivatives.funding",
                trial_count=3,
                grade="info",
                protocol="confirmatory",
                verdict="killed",
                maturity="L3",
                source="docs/hypotheses/08-funding-extremes.md",
                evidence="Trial ledger: +3",
                imported_at=company.clock.now(),
            )
        )
        session.flush()
        report = search(
            session,
            claim="Perpetual swap carry anticipates weekly drift.",
            family="info.derivatives.funding.crypto",
        )

    assert report.refs == ("MQ-H08",)
    assert report.matches[0].shared_family_depth == 3
    assert report.matches[0].origin == "fixture"


def test_family_distance_counts_shared_prefix_segments() -> None:
    assert family_distance("strategy.momentum.crypto", "strategy.momentum") == 2
    assert family_distance("strategy.momentum", "strategy.rotation") == 1
    assert family_distance("strategy", "info") == 0


def test_tokenise_drops_stopwords_and_short_words() -> None:
    assert tokenise("The funding rate is a signal") == frozenset(
        {"funding", "rate", "signal"}
    )


# ------------------------------------------------- acceptance (a): brainstorm


@needs_corpus
def test_a_brainstorm_pack_contains_what_was_tried_before(company: Runtime) -> None:
    """M6 acceptance (a).

    The room is handed the corpus before anybody speaks, so "have we tried
    this?" is answered from the record rather than from whatever the model
    associates with the words.
    """
    with company.database.session() as session:
        import_martex_corpus(
            session, ledger=company.ledger, clock=company.clock, graph=company.graph
        )
        pack, report, _rules = evidence_pack(
            session,
            question="Do funding-rate extremes predict forward returns?",
            family="info.derivatives.funding",
            ledger=company.ledger,
            at=company.clock.now(),
        )

    tried = pack["we_tried_this_before"]
    assert isinstance(tried, dict)
    assert tried["searched"] >= 21
    assert report.refs, "the funding hypothesis is in the corpus and must be found"
    assert any("funding" in art.family for art in report.matches)
    assert any(art.verdict == "killed" for art in report.matches)


@needs_corpus
def test_the_brainstorm_stores_its_prior_art_as_an_artifact(company: Runtime) -> None:
    with company.database.session() as session:
        import_martex_corpus(session, ledger=company.ledger, clock=company.clock)
        participants = tuple(
            company.roster.by_handle(session, handle).ref
            for handle in ("QUANT", "CRITIC", "GOV")
        )
        outcome = hold_brainstorm(
            session,
            chair=company.chair,
            question="Do funding-rate extremes predict forward returns?",
            family="info.derivatives.funding",
            chair_ref=participants[0],
            participants=participants,
            lessons=company.lessons,
            ledger=company.ledger,
            clock=company.clock,
        )
        kinds = {event.kind for event in company.ledger.tail(session, 400)}

    assert outcome.prior_art.searched >= 21
    assert outcome.prior_art.refs
    assert outcome.meeting.turns > 0
    assert EventKind.PRIOR_ART_SEARCHED in kinds


# ------------------------------------------------ acceptance (b): the corpus


@needs_corpus
def test_the_import_reproduces_the_corpus_own_claimed_totals(company: Runtime) -> None:
    """M6 acceptance (b).

    125 claimed, 120 documented, 5 carried. The gap is a real property of the
    source -- which says so itself -- and an importer that distributed it to
    make the arithmetic tidy would be fabricating a research record.
    """
    with company.database.session() as session:
        report = import_martex_corpus(
            session, ledger=company.ledger, clock=company.clock, graph=company.graph
        )
        stored = session.get(CorpusReconciliation, MARTEX_CORPUS)

    assert report.claimed_total == 125
    assert report.documented_total == 120
    assert report.unallocated == 5
    assert report.reconciles
    assert "reported, not absorbed" in report.unallocated_reason

    assert stored is not None
    assert stored.claimed_run == 124
    assert stored.claimed_data_blocked == 1
    assert stored.documented_total + stored.unallocated == stored.claimed_total
    assert stored.reconciles
    assert stored.entries == 21


@needs_corpus
def test_published_figures_are_preserved_not_recomputed(company: Runtime) -> None:
    """A DSR means "survived deflation against THAT many trials"."""
    with company.database.session() as session:
        import_martex_corpus(session, clock=company.clock)
        rows = {
            row.hypothesis: row
            for row in session.execute(
                sa.select(CorpusTrial).where(CorpusTrial.dsr.is_not(None))
            ).scalars()
        }

    assert rows["H11"].dsr == Decimal("0.99")
    assert rows["H11"].dsr_n_trials == 65
    assert rows["H12"].dsr == Decimal("0.777")
    assert rows["H12"].dsr_n_trials == 57
    assert rows["H43"].dsr_n_trials == 107
    assert len(rows) == 5

    # And character-for-character, not merely numerically. The money column
    # pads the scale to eight places, so "as published" needs its own field.
    assert rows["H11"].dsr_published == "0.99"
    assert rows["H12"].dsr_published == "0.777"
    assert rows["H43"].dsr_published == "1.0"


@needs_corpus
def test_the_import_is_idempotent_and_detects_a_changed_corpus(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        first = import_martex_corpus(session, clock=company.clock)
    with company.database.session() as session:
        second = import_martex_corpus(session, clock=company.clock)
        trials = session.execute(
            sa.select(sa.func.count()).select_from(CorpusTrial)
        ).scalar_one()

    assert not first.reimported
    assert second.reimported
    assert second.digest == first.digest
    assert trials == 21


@needs_corpus
def test_inherited_trials_are_marked_as_inherited(company: Runtime) -> None:
    """A reader must always be able to tell what Aurelis established itself."""
    with company.database.session() as session:
        import_martex_corpus(session, clock=company.clock, graph=company.graph)
        node = company.graph.node(session, "MQ-H11")
        rows = list(session.execute(sa.select(CorpusTrial)).scalars())

    assert node is not None
    assert node.origin == MARTEX_CORPUS
    assert node.kind == NodeKind.TRIAL
    assert all(row.corpus == MARTEX_CORPUS for row in rows)


@needs_corpus
def test_the_import_draws_no_edges_of_its_own(company: Runtime) -> None:
    """A link Aurelis invented between two of somebody else's trials would be
    this company's opinion wearing another organisation's citation."""
    with company.database.session() as session:
        import_martex_corpus(session, clock=company.clock, graph=company.graph)
        edges = session.execute(
            sa.select(sa.func.count()).select_from(KnowledgeEdge)
        ).scalar_one()
    assert edges == 0


@needs_corpus
def test_the_ambiguous_allocation_is_carried_not_divided(company: Runtime) -> None:
    with company.database.session() as session:
        import_martex_corpus(session, clock=company.clock)
        phase3 = session.execute(
            sa.select(CorpusTrial).where(CorpusTrial.hypothesis == "PHASE3")
        ).scalar_one()

    assert phase3.ambiguous_allocation
    assert phase3.trial_count == 38


def test_a_missing_corpus_is_an_error_not_an_empty_import(
    company: Runtime, tmp_path: Path
) -> None:
    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(CorpusNotAvailable):
            import_martex_corpus(session, bundle=tmp_path / "nothing")


# ------------------------------------------- acceptance (c): confidence drops


def _finding(
    company: Runtime,
    session: sa.orm.Session,
    *,
    verdict: Verdict = Verdict.CONFIRMED,
    supporters: int = 2,
) -> Finding:
    """A finding written by an agent that actually holds the scope to write one.

    Not a convenience: the write-scope triggers refuse an invented author, so
    the fixture has to obey the same permission model the company does.
    """
    author = company.roster.by_handle(session, "QUANT").ref
    finding = Finding(
        finding_id=uuid7(),
        ref="FND-9001",
        hypothesis_ref="HYP-9001",
        run_ref=None,
        statement="Momentum earns a positive Sharpe after costs.",
        verdict=verdict.value,
        verdict_reason="derived from the registered criteria",
        verdict_checks=[],
        author=author,
        created_at=company.clock.now(),
    )
    session.add(finding)
    session.add(
        Evidence(
            evidence_id=uuid7(),
            finding_ref="FND-9001",
            kind=EvidenceKind.OBSERVED_FACT.value,
            polarity=Polarity.SUPPORTS.value,
            statement="sharpe = 0.8 over the registered window",
            artifact_digest="a" * 64,
            author=author,
            created_at=company.clock.now(),
        )
    )
    company.graph.add_node(
        session, node_id="HYP-9001", kind=NodeKind.HYPOTHESIS, label="momentum"
    )
    for index in range(supporters):
        ref = f"FND-90{index + 10}"
        company.graph.add_node(
            session, node_id=ref, kind=NodeKind.FINDING, label=f"support {index}"
        )
        company.graph.relate(
            session,
            source=ref,
            target="HYP-9001",
            kind=EdgeKind.SUPPORTS,
            created_by=author,
        )
    session.flush()
    return finding


def _object_to(
    company: Runtime,
    session: sa.orm.Session,
    *,
    status: ObjectionStatus = ObjectionStatus.OPEN,
    severity: ObjectionSeverity = ObjectionSeverity.MAJOR,
) -> MeetingObjection:
    objection = MeetingObjection(
        objection_id=uuid7(),
        ref="OBJ-9001",
        meeting_ref="MTG-9001",
        author=company.roster.by_handle(session, "CRITIC").ref,
        target="HYP-9001",
        type=ObjectionType.SURVIVORSHIP.value,
        severity=severity.value,
        statement="The universe is the survivors list.",
        discriminating_test={},
        status=status.value,
        test_result={},
        created_at=company.clock.now(),
    )
    session.add(objection)
    session.flush()
    return objection


def test_confidence_degrades_when_an_objection_opens(company: Runtime) -> None:
    """M6 acceptance (c).

    Nothing about the finding changes. A doubt is filed against it, and the
    company is no longer entitled to believe it as strongly -- without anybody
    having to remember to update a column.
    """
    with company.database.session() as session:
        finding = _finding(company, session)
        before = assess(session, finding, graph=company.graph)

        _object_to(company, session)
        after = assess(session, finding, graph=company.graph)

    assert before.band == ConfidenceBand.MODERATE
    assert after.band == ConfidenceBand.WEAK
    assert after.band < before.band
    assert after.open_objections == 1
    assert "OBJ-9001 is an open major survivorship" in after.cap_reason


def test_a_critical_objection_takes_confidence_to_none(company: Runtime) -> None:
    with company.database.session() as session:
        finding = _finding(company, session)
        _object_to(company, session, severity=ObjectionSeverity.CRITICAL)
        confidence = assess(session, finding, graph=company.graph)
    assert confidence.band == ConfidenceBand.NONE


def test_resolving_an_objection_lifts_the_cap(company: Runtime) -> None:
    """Resolution restores the band. That is the incentive the design wants."""
    with company.database.session() as session:
        finding = _finding(company, session)
        objection = _object_to(company, session)
        capped = assess(session, finding, graph=company.graph)

        objection.status = ObjectionStatus.REJECTED.value
        session.flush()
        restored = assess(session, finding, graph=company.graph)

    assert capped.band == ConfidenceBand.WEAK
    assert restored.band == ConfidenceBand.MODERATE
    assert restored.open_objections == 0


def test_an_upheld_objection_is_not_merely_a_cap(company: Runtime) -> None:
    with company.database.session() as session:
        finding = _finding(company, session)
        _object_to(
            company,
            session,
            status=ObjectionStatus.UPHELD,
            severity=ObjectionSeverity.MINOR,
        )
        confidence = assess(session, finding, graph=company.graph)

    assert confidence.band == ConfidenceBand.NONE
    assert "was upheld by measurement" in confidence.cap_reason


def test_an_underpowered_verdict_is_an_abstention_not_weak_evidence(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        finding = _finding(company, session, verdict=Verdict.UNDERPOWERED)
        confidence = assess(session, finding, graph=company.graph)

    assert confidence.band == ConfidenceBand.NONE
    assert "underpowered" in confidence.cap_reason


def test_correlated_support_caps_confidence_and_explains_why(company: Runtime) -> None:
    with company.database.session() as session:
        finding = _finding(company, session, supporters=2)
        company.graph.relate(
            session,
            source="FND-9010",
            target="FND-9011",
            kind=EdgeKind.CORRELATED_WITH,
            weight=Decimal("0.85"),
            created_by="AG-0002",
        )
        confidence = assess(session, finding, graph=company.graph)

    assert confidence.band == ConfidenceBand.WEAK
    assert "support is not independent" in confidence.cap_reason


def test_confidence_with_no_reportable_evidence_is_none(company: Runtime) -> None:
    with company.database.session() as session:
        finding = _finding(company, session)
        session.execute(sa.delete(Evidence).where(Evidence.finding_ref == "FND-9001"))
        session.flush()
        confidence = assess(session, finding, graph=company.graph)

    assert confidence.band == ConfidenceBand.NONE
    assert "no reportable supporting evidence" in confidence.cap_reason


def test_only_the_explanation_is_stored_never_the_band(company: Runtime) -> None:
    with company.database.session() as session:
        finding = _finding(company, session)
        _object_to(company, session)
        confidence = assess(session, finding, graph=company.graph)
        write_cap_reason(session, confidence)
        stored = session.execute(
            sa.select(Finding).where(Finding.ref == "FND-9001")
        ).scalar_one()
        columns = {column.name for column in Finding.__table__.columns}

    assert "OBJ-9001" in stored.confidence_cap_reason
    assert "confidence" not in columns
    assert "confidence_cap_reason" in columns


# ------------------------------------------------------------------ lessons


def test_a_lesson_must_cite_where_it_came_from(company: Runtime) -> None:
    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(IntegrityViolation, match="must cite where it came from"):
            company.lessons.record(
                session, statement="Always use purged CV.", source_ref="  ", author="AG-0001"
            )


def test_a_standing_rule_must_name_what_it_binds(company: Runtime) -> None:
    """A rule with unlimited scope is how one desk's finding becomes doctrine."""
    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(IntegrityViolation, match="must name what it applies to"):
            company.lessons.record(
                session,
                statement="Never trust a Sharpe above 3.",
                source_ref="RTR-0001",
                author="AG-0001",
                standing_rule=True,
            )


def test_standing_rules_bind_a_family_subtree(company: Runtime) -> None:
    with company.database.session() as session:
        company.lessons.record(
            session,
            statement="Rotation claims must be tested against a delisted-inclusive universe.",
            source_ref="RTR-0001",
            author="AG-0001",
            standing_rule=True,
            applies_to=("strategy.rotation",),
        )
        company.lessons.record(
            session,
            statement="Funding-rate work needs an exchange-outage check.",
            source_ref="RTR-0002",
            author="AG-0001",
            standing_rule=True,
            applies_to=("info.derivatives",),
        )
        rotation = company.lessons.binding(session, family="strategy.rotation.crypto")
        elsewhere = company.lessons.binding(session, family="portfolio.sizing")

    assert [rule.ref for rule in rotation.rules] == ["LSN-0001"]
    assert elsewhere.rules == ()
    assert "no standing rules bind" in elsewhere.describe()


def test_a_retired_rule_stops_binding_but_is_not_deleted(company: Runtime) -> None:
    with company.database.session() as session:
        lesson = company.lessons.record(
            session,
            statement="Never run a backtest on Tuesdays.",
            source_ref="RTR-0003",
            author="AG-0001",
            standing_rule=True,
            applies_to=("*",),
        )
        company.lessons.retire(
            session, lesson.ref, reason="the finding behind it did not replicate"
        )
        binding = company.lessons.binding(session, family="strategy.momentum")
        still_there = company.lessons.live(session)
        kinds = {event.kind for event in company.ledger.tail(session, 200)}

    assert binding.rules == ()
    assert still_there == []
    assert EventKind.LESSON_RETIRED in kinds


def test_retiring_a_rule_requires_a_reason(company: Runtime) -> None:
    with company.database.session() as session:
        lesson = company.lessons.record(
            session,
            statement="Something.",
            source_ref="RTR-0004",
            author="AG-0001",
            standing_rule=True,
            applies_to=("*",),
        )
        with pytest.raises(IntegrityViolation, match="requires a reason"):
            company.lessons.retire(session, lesson.ref, reason="")


# -------------------------------------------------------------------- vault


def test_the_vault_is_generated_and_says_so(company: Runtime, tmp_path: Path) -> None:
    with company.database.session() as session:
        finding = _finding(company, session)
        company.lessons.record(
            session,
            statement="Correlated cells are not replication.",
            source_ref="RTR-0001",
            author="AG-0001",
        )
        report = export_vault(
            session,
            tmp_path / "vault",
            ledger=company.ledger,
            clock=company.clock,
            graph=company.graph,
        )

    page = (tmp_path / "vault" / "findings" / f"{finding.ref}.md").read_text(
        encoding="utf-8"
    )
    assert report.findings == 1
    assert "Generated file" in page
    assert "will be lost" in page
    assert "[[HYP-9001]]" in page
    assert "moderate" in page


def test_the_vault_module_offers_no_way_to_read_a_file_back() -> None:
    """The one-way constraint, asserted rather than trusted."""
    import aurelis.memory.vault as vault

    exported = {name for name in vault.__all__}
    assert exported == {"ExportReport", "export_vault"}
    source = Path(vault.__file__).read_text(encoding="utf-8")
    assert "read_text" not in source
    assert "loads(" not in source


@needs_corpus
def test_the_vault_records_the_reconciliation_gap(
    company: Runtime, tmp_path: Path
) -> None:
    with company.database.session() as session:
        import_martex_corpus(session, clock=company.clock, graph=company.graph)
        export_vault(session, tmp_path / "vault", clock=company.clock)

    index = (tmp_path / "vault" / "Corpus.md").read_text(encoding="utf-8")
    assert "**125**" in index
    assert "**120**" in index
    assert "unallocated: **5**" in index
    assert "carried, not distributed" in index

    trial = (tmp_path / "vault" / "trials" / "MQ-H11.md").read_text(encoding="utf-8")
    assert "Inherited from **martex-quant**" in trial
    assert "deflated against 65 trials (not recomputed)" in trial


def test_the_vault_lists_killed_research_first(company: Runtime, tmp_path: Path) -> None:
    """A corpus that only shows survivors has forgotten what it cost."""
    from aurelis.research.states import HypothesisState

    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        hypothesis = company.research.propose(
            session,
            claim="Something that will not survive.",
            author=quant,
            minimum_effect=Decimal("0.1"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
        )
        company.research.screen(
            session, hypothesis.ref, prior_art=(), shelve=True, reason="duplicate"
        )
        export_vault(session, tmp_path / "vault", clock=company.clock)
        state = company.research.hypothesis(session, hypothesis.ref).state

    index = (tmp_path / "vault" / "Corpus.md").read_text(encoding="utf-8")
    assert state == HypothesisState.SHELVED
    assert index.index("## Killed") < index.index("## All hypotheses")
    assert f"[[{hypothesis.ref}]]" in index


# ------------------------------------------------------------------ plumbing


def test_the_memory_tables_are_in_the_declared_schema() -> None:
    import aurelis.memory.tables as memory_tables
    from aurelis.schema import TABLE_MODULES

    assert memory_tables in TABLE_MODULES


def test_the_runtime_exposes_memory(company: Runtime) -> None:
    assert isinstance(company.graph, KnowledgeGraph)
    assert isinstance(company.lessons, Lessons)


def test_the_clock_is_honoured_everywhere(company: Runtime) -> None:
    """Nothing in memory reaches for the wall clock."""
    moment = dt.datetime(2030, 1, 1, tzinfo=dt.UTC)
    with company.database.session() as session:
        node = company.graph.add_node(
            session, node_id="LEAD-0001", kind=NodeKind.LEAD, label="anomaly", at=moment
        )
        lesson = company.lessons.record(
            session,
            statement="Leads are never findings.",
            source_ref="RTR-0009",
            author="AG-0001",
            at=moment,
        )
    assert node.created_at == moment
    assert lesson.created_at == moment


@needs_corpus
def test_the_title_is_read_from_the_source_document_not_invented(
    company: Runtime,
) -> None:
    """The corpus names its entries H08. The subject is in the filename."""
    with company.database.session() as session:
        import_martex_corpus(session, clock=company.clock)
        rows = {
            row.hypothesis: row.title
            for row in session.execute(sa.select(CorpusTrial)).scalars()
        }

    assert rows["H08"] == "funding extremes"
    assert rows["H52-H57"] == "intraday frontier"
    assert rows["PHASE3"] == "final selection"


@needs_corpus
def test_a_question_the_corpus_already_answered_is_not_reported_as_novel(
    company: Runtime,
) -> None:
    """The whole point of the import: asking again costs nothing to prevent."""
    with company.database.session() as session:
        import_martex_corpus(session, clock=company.clock)
        report = search(
            session,
            claim="Do funding rate extremes predict forward returns?",
            family="info.derivatives.funding",
        )

    assert not report.novel
    assert report.matches[0].ref == "MQ-H08"
    assert report.matches[0].strength == "close"
    assert report.matches[0].verdict == "killed"
    assert set(report.matches[0].matched_terms) >= {"funding", "extremes"}


# ------------------------------------------------------------------- mirror


def test_the_mirror_projects_research_onto_the_graph(company: Runtime) -> None:
    """The graph is derived from the record, not maintained alongside it."""
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        parent = company.research.propose(
            session,
            claim="Momentum earns a positive Sharpe after costs.",
            author=quant,
            minimum_effect=Decimal("0.05"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
            desk="crypto",
        )
        child = company.research.propose(
            session,
            claim="Momentum earns a positive Sharpe on the hourly bar too.",
            author=quant,
            minimum_effect=Decimal("0.05"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
            parent_ref=parent.ref,
            derivation="specialisation",
        )
        report = mirror_research(
            session, graph=company.graph, ledger=company.ledger, clock=company.clock
        )
        rests_on = company.graph.ancestors(session, child.ref)
        breaks_with = company.graph.descendants(session, parent.ref)

    assert report.hypotheses == 2
    assert report.nodes == 2
    assert report.edges == 1
    assert rests_on == [parent.ref]
    assert breaks_with == [child.ref]


def test_the_mirror_is_idempotent(company: Runtime) -> None:
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        company.research.propose(
            session,
            claim="Anything at all.",
            author=quant,
            minimum_effect=Decimal("0.05"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
        )
        first = mirror_research(session, graph=company.graph, clock=company.clock)
        second = mirror_research(session, graph=company.graph, clock=company.clock)

    assert first.nodes == 1
    assert second.nodes == 0
    assert second.edges == 0


def test_an_underpowered_finding_is_linked_neither_way(company: Runtime) -> None:
    """An abstention is not evidence, in either direction."""
    with company.database.session() as session:
        finding = _finding(company, session, verdict=Verdict.UNDERPOWERED)
        company.graph.add_node(
            session,
            node_id=finding.hypothesis_ref,
            kind=NodeKind.HYPOTHESIS,
            label="momentum",
        )
        mirror_research(session, graph=company.graph, clock=company.clock)
        support = company.graph.independent_support(session, finding.hypothesis_ref)
        edges = list(
            session.execute(
                sa.select(KnowledgeEdge).where(KnowledgeEdge.source == finding.ref)
            ).scalars()
        )

    assert edges == []
    assert finding.ref not in support.supporting


def test_mirror_edges_are_signed_by_the_mirror_not_an_agent(company: Runtime) -> None:
    """A derived edge and an asserted one must be distinguishable."""
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        parent = company.research.propose(
            session,
            claim="Parent claim.",
            author=quant,
            minimum_effect=Decimal("0.05"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
        )
        company.research.propose(
            session,
            claim="Child claim.",
            author=quant,
            minimum_effect=Decimal("0.05"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
            parent_ref=parent.ref,
            derivation="specialisation",
        )
        mirror_research(session, graph=company.graph, clock=company.clock)
        authors = {
            edge.created_by
            for edge in session.execute(sa.select(KnowledgeEdge)).scalars()
        }

    assert authors == {"mirror"}
