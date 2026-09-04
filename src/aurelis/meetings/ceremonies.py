"""Kickoff and Retrospective, as meetings.

M2 built the gates and let an operator satisfy them. This is the upgrade the
gates were designed for: the same ``Kickoff`` and ``Retrospective`` records,
now produced by a meeting that actually happened, with ``kind=MEETING`` rather
than ``OPERATOR``.

Nothing in the mission state machine changes. That was the point of writing the
gate as "a kickoff exists" rather than "a meeting happened" — the requirement
was always the artifact, and M3 changes only who is able to produce it.

The retrospective closes the forecasting loop: the kickoff's private
probabilities are scored against what the mission actually did, which is how a
per-agent quality signal accumulates without anyone grading anyone's prose.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aurelis.agents.roster import Roster
from aurelis.meetings.chair import Chair, MeetingOutcome, ProposedAction
from aurelis.meetings.forecasts import ForecastScorer
from aurelis.meetings.tables import Meeting
from aurelis.meetings.types import MeetingType
from aurelis.missions.missions import Missions
from aurelis.missions.states import KickoffKind, MissionState, ProjectState

__all__ = ["KICKOFF_QUESTION", "hold_kickoff", "hold_retrospective"]

KICKOFF_QUESTION = (
    "Will this mission finish every task it plans, without any being cancelled "
    "or refused for budget?"
)
"""The forecast every kickoff records.

Deliberately about *execution* rather than about whether the research will
find something. A question the retrospective can settle from the record is
worth more than a more interesting one nobody can resolve — an unresolvable
forecast is never scored, and an unscored forecast teaches nobody anything.
"""


@dataclass(frozen=True, slots=True)
class Ceremony:
    """A held ceremony and the record it produced."""

    meeting: MeetingOutcome
    record_ref: str


def hold_kickoff(
    session: Session,
    *,
    chair: Chair,
    missions: Missions,
    roster: Roster,
    subject_ref: str,
    participants: tuple[str, ...],
    chair_ref: str,
    evidence: dict[str, object] | None = None,
    actions: tuple[ProposedAction, ...] = (),
    desk: str | None = None,
    at: dt.datetime | None = None,
) -> Ceremony:
    """Hold a Kickoff and let its plan satisfy the mission's gate.

    The synthesis *is* the plan. That is the whole design: a meeting whose
    output did not become the thing the state machine requires would be a
    meeting held for its own sake.
    """
    if subject_ref.startswith("MSN-"):
        objective = missions.mission(session, subject_ref).objective
    else:
        objective = missions.project(session, subject_ref).intent

    meeting = chair.convene(
        session,
        meeting_type=MeetingType.KICKOFF,
        subject=f"Kickoff: {objective[:180]}",
        chair=chair_ref,
        participants=participants,
        subject_ref=subject_ref,
        trigger="mission state machine requires a kickoff before work begins",
        desk=desk,
        evidence={"objective": objective, **(evidence or {})},
        at=at,
    )
    outcome = chair.run(
        session,
        meeting.ref,
        forecast_question=KICKOFF_QUESTION,
        actions=actions,
        at=at,
    )

    kickoff = missions.record_kickoff(
        session,
        subject_ref=subject_ref,
        plan=outcome.synthesis or "(the meeting produced no plan)",
        participants=participants,
        kind=KickoffKind.MEETING,
        authorised_by=meeting.ref,
        at=at,
    )
    return Ceremony(meeting=outcome, record_ref=kickoff.ref)


def hold_retrospective(
    session: Session,
    *,
    chair: Chair,
    missions: Missions,
    roster: Roster,
    scorer: ForecastScorer,
    subject_ref: str,
    participants: tuple[str, ...],
    chair_ref: str,
    kickoff_meeting_ref: str | None = None,
    desk: str | None = None,
    at: dt.datetime | None = None,
) -> Ceremony:
    """Hold a Retrospective, score the kickoff's forecasts, record the lessons.

    The outcome counts go into the evidence pack **before** anyone speaks, so
    the room is discussing what actually happened rather than what it
    remembers happening — including the failures.
    """
    progress = missions.progress(session, subject_ref)
    spent = missions.spent(session, subject_ref)

    meeting = chair.convene(
        session,
        meeting_type=MeetingType.RETROSPECTIVE,
        subject=f"Retrospective: {subject_ref}",
        chair=chair_ref,
        participants=participants,
        subject_ref=subject_ref,
        trigger="mission state machine requires a retrospective before closing",
        desk=desk,
        evidence={
            "outcomes": {
                "total": progress.total,
                "succeeded": progress.succeeded,
                "failed": progress.failed,
                "refused_budget": progress.refused_budget,
                "cancelled": progress.cancelled,
            },
            "spent_tokens": spent.tokens,
            "what_we_predicted": KICKOFF_QUESTION,
        },
        at=at,
    )
    outcome = chair.run(session, meeting.ref, at=at)

    # The kickoff's forecast, settled by the record rather than by opinion.
    if kickoff_meeting_ref is not None:
        clean = (
            progress.total > 0
            and progress.succeeded == progress.total
        )
        scorer.score(
            session,
            meeting_ref=kickoff_meeting_ref,
            outcome=clean,
            against=meeting.ref,
            at=at,
        )

    lessons = tuple(
        line.strip("-• ").strip()
        for line in outcome.synthesis.splitlines()
        if line.strip().startswith(("-", "•"))
    )
    record = missions.record_retrospective(
        session,
        subject_ref=subject_ref,
        summary=outcome.synthesis or "(the meeting produced no summary)",
        lessons=lessons,
        kind=KickoffKind.MEETING,
        authorised_by=meeting.ref,
        at=at,
    )
    return Ceremony(meeting=outcome, record_ref=record.ref)


def close_out(
    session: Session,
    missions: Missions,
    subject_ref: str,
    *,
    reason: str = "work complete",
    at: dt.datetime | None = None,
) -> None:
    """Walk a mission or project through REVIEWING to CLOSED."""
    is_project = subject_ref.startswith("PRJ-")
    reviewing = ProjectState.REVIEWING if is_project else MissionState.REVIEWING
    closed = ProjectState.CLOSED if is_project else MissionState.CLOSED
    missions.transition(session, subject_ref, reviewing, at=at)
    missions.transition(session, subject_ref, closed, reason=reason, at=at)


def kickoff_meeting_ref(session: Session, subject_ref: str) -> str | None:
    """The Kickoff meeting held for a subject, if one was."""
    import sqlalchemy as sa

    return session.execute(
        sa.select(Meeting.ref)
        .where(
            Meeting.subject_ref == subject_ref,
            Meeting.type == MeetingType.KICKOFF.value,
        )
        .order_by(Meeting.convened_at)
        .limit(1)
    ).scalar_one_or_none()
