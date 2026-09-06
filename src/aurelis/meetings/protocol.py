"""What each meeting type actually does, and what it may spend.

Meetings are the most expensive thing the company does, so every type declares
its phases, its caps and its model tiers up front. The Chair enforces them, and
running out of meeting moves straight to synthesis rather than failing — a
half-finished discussion with the unresolved threads written down as follow-up
tasks is a normal outcome.

The tier ladder is where most of the saving is. Convening, briefing, speaker
selection, claim extraction, test dispatch and minute-writing are deterministic
and cost nothing. Forecasts are a single low-tier call each. Only the exchange,
where the thinking happens, runs at the participants' own tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aurelis.core.enums import ModelTier
from aurelis.meetings.types import MeetingType, Phase

__all__ = ["PROTOCOLS", "Protocol", "protocol_for"]


@dataclass(frozen=True, slots=True)
class Protocol:
    """One meeting type's shape and limits."""

    type: MeetingType
    purpose: str
    phases: tuple[Phase, ...]

    max_participants: int = 8
    max_exchange_rounds: int = 2
    max_tokens_total: int = 12_000
    max_tokens_per_turn: int = 600
    """Keeps one agent from consuming the room."""

    max_test_dispatches: int = 3
    """The compute budget for discriminating tests. An objection that cannot
    be settled inside it becomes a follow-up task rather than stalling the
    meeting."""

    opening_tier: ModelTier = ModelTier.LOW
    exchange_tier: ModelTier = ModelTier.MID
    synthesis_tier: ModelTier = ModelTier.MID
    forecast_tier: ModelTier = ModelTier.LOW

    requires_decision: bool = True
    """False for a Brainstorm: its productive output is candidate questions,
    and demanding a decision would push a divergent meeting into converging
    before it has anything to converge on."""

    speculation_allowed: bool = False
    """Brainstorms only. Marked as such, and nothing said in one may become
    evidence for anything."""

    scores_forecasts: bool = False
    """Retrospectives close the loop on the kickoff's forecasts."""

    agenda: tuple[str, ...] = field(default_factory=tuple)


PROTOCOLS: dict[MeetingType, Protocol] = {
    MeetingType.KICKOFF: Protocol(
        type=MeetingType.KICKOFF,
        purpose="Agree what this mission is doing, and who does what.",
        phases=(
            Phase.BRIEF,
            Phase.FORECAST,
            Phase.OPENING,
            Phase.EXCHANGE,
            Phase.SYNTHESIS,
            Phase.DECIDE,
        ),
        max_exchange_rounds=2,
        max_tokens_total=15_000,
        agenda=(
            "What is the objective, in one sentence?",
            "What would have to be true for this to be worth doing?",
            "What is the first piece of work, and who does it?",
            "What would make us stop?",
        ),
    ),
    MeetingType.STANDUP: Protocol(
        type=MeetingType.STANDUP,
        purpose="Status deltas and blockers. Deliberately cheap.",
        phases=(Phase.BRIEF, Phase.OPENING, Phase.SYNTHESIS),
        max_exchange_rounds=0,
        max_tokens_total=4_000,
        max_tokens_per_turn=250,
        opening_tier=ModelTier.LOW,
        synthesis_tier=ModelTier.LOW,
        requires_decision=False,
        agenda=("What moved?", "What is blocked, and on what?"),
    ),
    MeetingType.BRAINSTORM: Protocol(
        type=MeetingType.BRAINSTORM,
        purpose="Diverge. Produce candidate questions, not conclusions.",
        phases=(Phase.BRIEF, Phase.OPENING, Phase.EXCHANGE, Phase.SYNTHESIS),
        max_exchange_rounds=3,
        max_tokens_total=14_000,
        requires_decision=False,
        speculation_allowed=True,
        agenda=(
            "What is unusual here?",
            "What would we expect if the obvious explanation were wrong?",
            "What has been tried before, and what happened?",
        ),
    ),
    MeetingType.STRATEGY_COMMITTEE: Protocol(
        type=MeetingType.STRATEGY_COMMITTEE,
        purpose="Deploy a composed version, or refuse it. Gates decide; the "
        "room decides what to do about what the gates said.",
        phases=(
            Phase.BRIEF,
            Phase.FORECAST,
            Phase.OPENING,
            Phase.CHALLENGE,
            Phase.SYNTHESIS,
            Phase.DECIDE,
        ),
        max_exchange_rounds=1,
        max_tokens_total=16_000,
        requires_decision=True,
        agenda=(
            "Which gates passed, and against criteria registered when?",
            "What did the authors name as this version's known weaknesses?",
            "How much of this did we write, and how much did we inherit?",
            "Where has it actually been measured, and where is it unproven?",
        ),
    ),
    MeetingType.RISK_COMMITTEE: Protocol(
        type=MeetingType.RISK_COMMITTEE,
        purpose="Set, tighten or lift limits. Risk holds the pen.",
        phases=(Phase.BRIEF, Phase.OPENING, Phase.SYNTHESIS, Phase.DECIDE),
        max_exchange_rounds=1,
        max_tokens_total=10_000,
        requires_decision=True,
        agenda=(
            "What exposure is being requested, and on what evidence?",
            "Which limits bind it, and why do they exist?",
            "What would have to be true for this limit to be wrong?",
        ),
    ),
    MeetingType.RESEARCH_REVIEW: Protocol(
        type=MeetingType.RESEARCH_REVIEW,
        purpose="Challenge a finding, and settle the challenge with a test.",
        phases=(
            Phase.BRIEF,
            Phase.FORECAST,
            Phase.OPENING,
            Phase.EXCHANGE,
            Phase.CHALLENGE,
            Phase.SYNTHESIS,
            Phase.DECIDE,
        ),
        max_exchange_rounds=2,
        max_tokens_total=18_000,
        max_test_dispatches=4,
        agenda=(
            "What is claimed, and what supports it?",
            "What is the strongest reason it might be wrong?",
            "What test would settle that?",
            "Does the claim survive?",
        ),
    ),
    MeetingType.BOARD: Protocol(
        type=MeetingType.BOARD,
        purpose="Decide a change to the company itself, against a prediction "
        "that was locked before anyone in the room saw it.",
        phases=(
            Phase.BRIEF,
            Phase.FORECAST,
            Phase.OPENING,
            Phase.EXCHANGE,
            Phase.SYNTHESIS,
            Phase.DECIDE,
        ),
        max_exchange_rounds=1,
        max_tokens_total=14_000,
        requires_decision=True,
        agenda=(
            "What measurement fired, and against which declared threshold?",
            "What does the proposal predict, and how will that be checked?",
            "What breaks if this is wrong, and who picks up the work?",
            "What would we expect to see if the change made no difference?",
        ),
    ),
    MeetingType.RETROSPECTIVE: Protocol(
        type=MeetingType.RETROSPECTIVE,
        purpose="What happened, what was learned, and how good our forecasts were.",
        phases=(
            Phase.BRIEF,
            Phase.OPENING,
            Phase.EXCHANGE,
            Phase.SYNTHESIS,
            Phase.DECIDE,
        ),
        max_exchange_rounds=1,
        max_tokens_total=12_000,
        scores_forecasts=True,
        agenda=(
            "What did we predict, and what actually happened?",
            "What would we do differently?",
            "What should become a standing rule?",
        ),
    ),
}


def protocol_for(meeting_type: MeetingType) -> Protocol:
    try:
        return PROTOCOLS[meeting_type]
    except KeyError:
        raise KeyError(
            f"no protocol for {meeting_type}. Meeting types are a closed "
            "registry; a type without declared phases and caps would be an "
            "unbudgeted conversation."
        ) from None
