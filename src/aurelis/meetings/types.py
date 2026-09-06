"""The vocabulary of a meeting.

Every one of these is a closed enum rather than free text, for the same reason
throughout Aurelis: a transcript you can query is worth vastly more than a
transcript you can only read, and a value that can be invented at runtime
cannot be reviewed.

The one that carries the most weight is :class:`Stance`. It is what lets the
Chair select speakers by genuine disagreement rather than by eagerness, and it
is what makes ``changed_mind_from`` meaningful — an agent that updates on
evidence is doing the job, and one that never updates, or always updates, is a
measured problem rather than an impression.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "Attendance",
    "MeetingStatus",
    "MeetingType",
    "ObjectionSeverity",
    "ObjectionType",
    "Phase",
    "Stance",
    "TurnKind",
]


class MeetingType(StrEnum):
    """Meeting types arrive with the layers whose decisions they exist to make.

    A Strategy Committee with no strategies to promote would be a room with
    nothing in it, so the committees appeared at M8 and M9. The Board appeared
    at M11, when the company first had a structural change to decide.
    """

    KICKOFF = "kickoff"
    """Mandatory at the start of every mission and project."""

    STANDUP = "standup"
    """Cheap. Status deltas and blockers, one round, no decision required."""

    BRAINSTORM = "brainstorm"
    """Divergent. Speculation is allowed and marked; nothing said here can
    become evidence for anything."""

    RESEARCH_REVIEW = "research_review"
    """Where a finding is challenged. The only M3 type with a CHALLENGE phase,
    because it is the only one that has something to test."""

    STRATEGY_COMMITTEE = "strategy_committee"
    """Decides whether a composed version is deployed. Risk and Audit are
    required, not invited: a promotion meeting without the roles that can
    refuse it is a ceremony."""

    RISK_COMMITTEE = "risk_committee"
    """Sets and reviews limits. Convened by Risk, and the only meeting whose
    decisions bind other departments without their agreement."""

    RETROSPECTIVE = "retrospective"
    """Mandatory at the end. Scores the kickoff's forecasts against what
    actually happened, and extracts lessons."""

    BOARD = "board"
    """Decides changes to the company itself. The only meeting whose subject
    is the organisation rather than the market, and the only one where the
    proposal in front of the room carries a **locked** prediction the room
    cannot influence (ADR-0012)."""


class Phase(StrEnum):
    """The seven phases, in order.

    ``CONVENE`` is deliberately absent: assembling the agenda, the evidence
    pack and the participant list is how a meeting is *constructed*, not
    something that happens inside one. It costs no model call.
    """

    BRIEF = "brief"
    """Deterministic. The same state of the world for everyone, rendered from
    the record — no information asymmetry by accident."""

    FORECAST = "forecast"
    """Each participant privately records a probability BEFORE hearing anyone.
    The defence against an agreement cascade, and the company's cheapest
    honest quality signal."""

    OPENING = "opening"
    """One bounded turn each. Everyone speaks exactly once."""

    EXCHANGE = "exchange"
    """The actual discussion. Capped rounds; the Chair selects speakers by
    stance conflict."""

    CHALLENGE = "challenge"
    """Objections are formalised, each carrying a discriminating test the
    Chair actually dispatches."""

    SYNTHESIS = "synthesis"
    """One draft of the outcome."""

    DECIDE = "decide"
    """Typed decision with dissent preserved; action items become real tasks."""


PHASE_ORDER: tuple[Phase, ...] = (
    Phase.BRIEF,
    Phase.FORECAST,
    Phase.OPENING,
    Phase.EXCHANGE,
    Phase.CHALLENGE,
    Phase.SYNTHESIS,
    Phase.DECIDE,
)


class MeetingStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_SESSION = "in_session"
    SYNTHESISING = "synthesising"
    CLOSED = "closed"
    ABANDONED = "abandoned"
    """Convened but could not proceed — no participants, or the subject
    vanished. Recorded rather than deleted."""


class Attendance(StrEnum):
    """Who is in the room, and why.

    This is how meetings scale. At a hundred agents a Research Review still has
    six people in it and ninety-four reading the minutes, because attendance is
    resolved from the subject rather than from who is available.
    """

    CHAIR = "chair"
    REQUIRED = "required"
    """Their write scope covers the decision. Risk for a risk decision, the
    Head of Strategy for a promotion."""

    CONTRIBUTING = "contributing"
    """Has relevant evidence or a genuine stance conflict."""

    OBSERVING = "observing"
    """Receives the minutes, does not speak, costs nothing."""


class TurnKind(StrEnum):
    POSITION = "position"
    ARGUMENT = "argument"
    QUESTION = "question"
    ANSWER = "answer"
    EVIDENCE = "evidence"
    OBJECTION = "objection"
    CONCESSION = "concession"
    PROPOSAL = "proposal"
    SYNTHESIS = "synthesis"
    BRIEF = "brief"
    """The Chair's deterministic opening. Costs nothing and is recorded as a
    turn so the transcript is complete."""


class Stance(StrEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    UNCERTAIN = "uncertain"
    ABSTAINS = "abstains"

    @property
    def is_committed(self) -> bool:
        return self in (Stance.SUPPORTS, Stance.OPPOSES)


def opposing(left: Stance, right: Stance) -> bool:
    """Whether two stances genuinely conflict.

    Uncertainty is not conflict. A room where everyone is unsure needs more
    evidence, not more argument.
    """
    return (
        left.is_committed
        and right.is_committed
        and left is not right
    )


class ObjectionType(StrEnum):
    """A closed taxonomy, so objections can be scored.

    Closed rather than free text for a specific future reason: at M10 the
    training-scenario suite plants known defects and counts which agents catch
    them, and a free-text objection cannot be matched against a planted
    defect.

    The market types each have a **mechanical test builder** in
    :mod:`aurelis.meetings.taxonomy`: a Critic names the defect and the varied
    specification is generated, so the test's construction is written down and
    identical every time the same defect is alleged.
    """

    # General research defects.
    WEAK_BASELINE = "weak_baseline"
    CONFOUND = "confound"
    ALTERNATIVE_EXPLANATION = "alternative_explanation"
    UNDERPOWERED = "underpowered"
    METRIC_INVALID = "metric_invalid"
    SEED_INSTABILITY = "seed_instability"
    GENERALISATION_OVERREACH = "generalisation_overreach"
    IMPLEMENTATION_BUG = "implementation_bug"
    DATA_QUALITY = "data_quality"
    UNSOURCED_CLAIM = "unsourced_claim"

    # Market defects. Each has a mechanical test.
    SURVIVORSHIP = "survivorship"
    """The universe was chosen knowing which names survived."""

    LOOKAHEAD = "lookahead"
    COST_UNDERSTATED = "cost_understated"
    LIQUIDITY_UNREALISTIC = "liquidity_unrealistic"
    REGIME_SPECIFIC = "regime_specific"
    CAPACITY_IGNORED = "capacity_ignored"
    CROWDING = "crowding"
    DATA_REVISION = "data_revision"


class ObjectionSeverity(StrEnum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"
    """Gates promotion while open. Nothing may be accepted over one."""


class ObjectionStatus(StrEnum):
    OPEN = "open"
    UPHELD = "upheld"
    """The discriminating test ran and the objection was right."""

    REJECTED = "rejected"
    """The test ran and the objection was wrong. Recorded either way — a
    critic's false-alarm rate is as measurable as its hit rate."""

    UNTESTABLE = "untestable"
    """No test could settle it within the meeting's compute budget. Reported
    as an unresolved limitation rather than silently dropped."""
