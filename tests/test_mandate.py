"""M20 — the company decides whether it is ready, and asks.

The endpoint of this project is not a live adapter somebody switches on. It is
the company reaching the judgement itself, on evidence it gathered, and telling
the person who would have to fund it.

The acceptance is a refusal. After running everything this company knows how to
do — staffing, a research review, seven desks, an authored strategy, a campaign
with its correction — it meets **four of ten** conditions and says so. A
standard the current evidence passed would be a standard written to pass.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.authoring.campaign import run_campaign
from aurelis.authoring.standin import scripted_author
from aurelis.core.ids import uuid7
from aurelis.mandate.assessment import NOT_YET, READY, Finding, MandateOutcome, assess, history
from aurelis.mandate.standard import STANDARD, Criterion, digest
from aurelis.mandate.tables import MandateAssessment
from aurelis.platform.llm.providers import MockProvider
from aurelis.runtime import Runtime


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


# ------------------------------------------------------------- the standard


def test_the_standard_is_declared_in_advance_and_hashed() -> None:
    """A bar lowered after it was missed is the one change that would make all
    of this worthless. The digest is what makes such a change impossible to
    make quietly."""
    assert len(STANDARD) == 10
    assert len({c.key for c in STANDARD}) == len(STANDARD)
    assert digest() == digest(), "the hash is stable across calls"
    assert all(c.asks.endswith("?") for c in STANDARD), "each one is a question"
    assert all(c.why for c in STANDARD), "and each says why it is there"


def test_the_first_condition_is_the_one_it_cannot_argue_around() -> None:
    """Everything else could be satisfied on fixtures, and satisfying them on
    fixtures would prove the machinery works rather than that a market has an
    edge in it. So it is asked first."""
    assert STANDARD[0].key == "live_data"


def test_nothing_is_blocked_any_more() -> None:
    """The difference between a to-do list and a result, and the to-do list is
    now empty.

    M20 reported two conditions that no amount of research could satisfy: no
    desk had a wired feed, and nothing wrote a replication record. M21 built
    both, so every remaining condition is a research result rather than a
    missing capability -- which is a much harder place for the company to be.
    """
    blocked = {c.key for c in STANDARD if c.blocked}
    assert blocked == set(), (
        "a blocked criterion names machinery that does not exist; there is "
        "none left, so every unmet condition is now the company's own problem"
    )
    for criterion in STANDARD:
        assert not criterion.blocked_by


# ------------------------------------------------------ the honest answer


def test_a_company_that_has_done_nothing_is_not_ready(company: Runtime) -> None:
    outcome = assess(company)
    assert outcome.verdict == NOT_YET
    assert not outcome.ready
    assert outcome.escalated_to is None
    assert not outcome.blocked, "M21 left nothing the company cannot attempt"
    assert len(outcome.findings) == len(STANDARD)
    assert len(outcome.unmet) > len(outcome.met), (
        "a fresh company has done nothing, and the standard says so"
    )


def test_a_company_that_has_done_everything_is_still_not_ready(
    company: Runtime,
) -> None:
    """The acceptance.

    An authored strategy, a campaign, the selection correction applied. The
    company is further along and still refuses, and the reading on each unmet
    condition says exactly what it is short by.
    """
    run_campaign(company, span=Decimal("0.1"), budget=3)
    outcome = assess(company)

    assert outcome.verdict == NOT_YET
    assert {f.criterion.key for f in outcome.met} >= {"authored", "chain_intact"}
    assert any(f.criterion.key == "survived_selection" for f in outcome.unmet)
    surplus = next(
        f for f in outcome.unmet if f.criterion.key == "survived_selection"
    )
    assert "surplus" in surplus.reading, "it says by how much, not just that it failed"


def test_every_condition_reports_a_reading_either_way(company: Runtime) -> None:
    """An unmet criterion that could not say what it found would be an
    assertion rather than a measurement."""
    outcome = assess(company)
    for finding in outcome.findings:
        assert finding.reading.strip(), f"{finding.criterion.key} said nothing"


def test_a_critic_that_was_right_does_not_disqualify_the_company(
    company: Runtime,
) -> None:
    """The bug running this found.

    The first version required no upheld objection anywhere, so a company whose
    critic had correctly killed a biased claim read as unready *because its
    critic worked*. Upheld and rejected are settled; what disqualifies is an
    objection nobody resolved.
    """
    reviewed = next(c for c in STANDARD if c.key == "reviewed")
    with company.database.session() as session:
        # A Critic, because the database refuses an objection from an
        # agent whose charters do not grant the scope -- which it did,
        # the first time this test hard-coded an executive.
        critic = company.roster.by_handle(session, "CRITIC").ref
        session.execute(
            sa.text(
                "INSERT INTO meeting_objections (objection_id, ref, meeting_ref, "
                "author, target, type, severity, statement, discriminating_test, "
                "test_result, status, created_at) VALUES "
                "(:i, 'OBJ-9001', 'MTG-9001', :a, 'HYP-0001', 'survivorship', "
                "'major', 'the universe was chosen with hindsight', '{}', '{}', "
                "'upheld', :t)"
            ),
            {
                "i": uuid7().bytes,
                "a": critic,
                "t": dt.datetime(2026, 9, 8, tzinfo=dt.UTC),
            },
        )
        session.flush()
        met, reading = reviewed.check(session)

    assert met, "an objection that was tested and upheld is the process working"
    assert "upheld" in reading


def test_an_objection_nobody_settled_does_disqualify(company: Runtime) -> None:
    reviewed = next(c for c in STANDARD if c.key == "reviewed")
    with company.database.session() as session:
        # A Critic, because the database refuses an objection from an
        # agent whose charters do not grant the scope -- which it did,
        # the first time this test hard-coded an executive.
        critic = company.roster.by_handle(session, "CRITIC").ref
        session.execute(
            sa.text(
                "INSERT INTO meeting_objections (objection_id, ref, meeting_ref, "
                "author, target, type, severity, statement, discriminating_test, "
                "test_result, status, created_at) VALUES "
                "(:i, 'OBJ-9002', 'MTG-9002', :a, 'HYP-0001', 'survivorship', "
                "'major', 'nobody ran the test', '{}', '{}', 'open', :t)"
            ),
            {
                "i": uuid7().bytes,
                "a": critic,
                "t": dt.datetime(2026, 9, 8, tzinfo=dt.UTC),
            },
        )
        session.flush()
        met, reading = reviewed.check(session)

    assert not met
    assert "still standing" in reading


# --------------------------------------------------------- the record kept


def test_a_refusal_interrupts_nobody_and_is_kept_anyway(company: Runtime) -> None:
    """A system that pinged its owner every time it looked would train them to
    stop reading. A company that kept only the assessment that passed could not
    show the bar had ever held."""
    first = assess(company)
    second = assess(company)

    with company.database.session() as session:
        rows = history(session)
    assert len(rows) == 2
    assert all(row.escalated_to is None for row in rows)
    assert {row.ref for row in rows} == {first.ref, second.ref}
    assert all(row.verdict == NOT_YET for row in rows)


def test_every_assessment_records_which_bar_it_was_judged_against(
    company: Runtime,
) -> None:
    outcome = assess(company)
    with company.database.session() as session:
        row = session.execute(
            sa.select(MandateAssessment).where(MandateAssessment.ref == outcome.ref)
        ).scalar_one()
    assert row.standard_digest == digest()
    assert row.criteria == len(STANDARD)
    assert row.findings["criteria"], "the readings are kept, not just the verdict"


def test_a_standard_that_moved_between_assessments_is_surfaced(
    company: Runtime, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    """Fired on its own author the first time it ran: the ``reviewed``
    criterion was fixed between two assessments and the next report said so."""
    assess(company)

    from aurelis.mandate import assessment as module

    monkeypatch.setattr(module, "digest", lambda: "0" * 64)
    moved = assess(company)

    assert moved.standard_changed
    assert moved.previous_digest == digest()
    assert moved.as_payload()["standard_changed"] is True


# ------------------------------------------------------------- the ask


def test_ready_means_every_condition_and_escalates() -> None:
    """There is no third verdict. A company that could report "nearly" would
    eventually report it about everything."""
    findings = tuple(
        Finding(criterion=c, met=True, reading="satisfied") for c in STANDARD
    )
    outcome = MandateOutcome(
        ref="MDT-0001",
        standard_digest=digest(),
        findings=findings,
        escalated_to="OPERATOR",
        assessed_at=dt.datetime(2026, 9, 8, tzinfo=dt.UTC),
    )
    assert outcome.ready
    assert outcome.verdict == READY
    assert not outcome.unmet
    assert "READY" in outcome.describe()
    assert outcome.escalated_to == "OPERATOR"


def test_the_database_refuses_a_ready_with_anything_unmet(company: Runtime) -> None:
    """The whole milestone in a constraint. Enforced by the database rather
    than by the function that writes the row, because the function is one edit
    away from being generous with itself."""
    with company.database.session() as session:
        try:
            session.add(
                MandateAssessment(
                    assessment_id=uuid7(),
                    ref="MDT-9999",
                    standard_digest=digest(),
                    criteria=10,
                    met=9,
                    blocked=0,
                    verdict=READY,
                    findings={},
                    escalated_to="OPERATOR",
                    assessed_at=dt.datetime(2026, 9, 8, tzinfo=dt.UTC),
                )
            )
            session.flush()
        except Exception as error:  # noqa: BLE001 - the database raises, not us
            session.rollback()
            message = str(error)
        else:  # pragma: no cover - reaching this is the failure
            message = ""

    assert "ck_mandate_ready_means_every_criterion" in message


def test_a_verdict_outside_the_two_words_is_refused(company: Runtime) -> None:
    with company.database.session() as session:
        try:
            session.add(
                MandateAssessment(
                    assessment_id=uuid7(),
                    ref="MDT-9998",
                    standard_digest=digest(),
                    criteria=10,
                    met=4,
                    blocked=2,
                    verdict="nearly",
                    findings={},
                    assessed_at=dt.datetime(2026, 9, 8, tzinfo=dt.UTC),
                )
            )
            session.flush()
        except Exception as error:  # noqa: BLE001
            session.rollback()
            message = str(error)
        else:  # pragma: no cover
            message = ""

    assert "ck_mandate_verdict_is_binary" in message


def test_a_criterion_is_a_question_with_a_check() -> None:
    """The type carries both, so a condition cannot be declared without a way
    of settling it."""
    for criterion in STANDARD:
        assert isinstance(criterion, Criterion)
        assert callable(criterion.check)
