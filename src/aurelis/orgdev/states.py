"""The vocabulary of an organisational change.

Closed enums, for the same reason the objection taxonomy is closed: at some
point the company will be asked "which kinds of change actually helped?", and a
free-text ``kind`` makes that question unanswerable.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "APPLICABLE_STATES",
    "EffectVerdict",
    "OrgChangeKind",
    "OrgChangeState",
    "TriggerKind",
]


class OrgChangeKind(StrEnum):
    """What is being proposed."""

    FISSION = "fission"
    """Split one agent's coverage and staff the split-off part."""

    FUSION = "fusion"
    """Merge two agents' coverage into one and retire the other."""

    HIRE = "hire"
    """Staff a charter area nobody currently stands in for. Rare by
    construction — every charter is owned from launch — and reserved for a
    desk opening."""

    RETRAIN = "retrain"
    """An agent failed the scenario suite for its specialty. Its procedure is
    revised and it is scored again."""

    CLOSE = "close"
    """Stop covering something, explicitly and with a reason. Not currently
    reachable: the coverage invariant refuses to orphan a charter, so closing
    one means retiring it from the registry, which is a code change and a
    review. The member exists so that "we stopped doing this" has somewhere to
    be recorded when it happens."""


class OrgChangeState(StrEnum):
    """Where a proposal is.

    ``LOCKED`` is the one that matters. A proposal's predicted effect and
    measurement plan are hashed before the room sees it, exactly as a research
    preregistration is hashed before a run — because a prediction that can be
    edited after the outcome is not a prediction (ADR-0012).
    """

    DRAFT = "draft"
    LOCKED = "locked"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    MEASURED = "measured"
    WITHDRAWN = "withdrawn"


APPLICABLE_STATES = frozenset({OrgChangeState.APPROVED})
"""The only state a change may be applied from. Not DRAFT, and not LOCKED: a
proposal nobody decided on is not a decision."""


class EffectVerdict(StrEnum):
    """What the change actually did, measured after the declared window."""

    IMPROVED = "improved"
    """The predicted metric moved the predicted way, by at least the
    predicted amount."""

    PARTIAL = "partial"
    """It moved the right way and fell short of what was predicted. A real
    result, and not a success."""

    NO_CHANGE = "no_change"
    WORSE = "worse"
    UNMEASURABLE = "unmeasurable"
    """The metric could not be computed on both sides of the window. Never
    counted as a success, and it names what was missing."""


class TriggerKind(StrEnum):
    """Why a change was proposed. Measured, never guessed."""

    BACKLOG_DEPTH = "backlog_depth"
    RESPONSE_LATENCY = "response_latency"
    COVERAGE_STARVATION = "coverage_starvation"
    OUTPUT_OVERLAP = "output_overlap"
    UNDERUSE = "underuse"
    SCENARIO_FAILURE = "scenario_failure"
    CALIBRATION_DECAY = "calibration_decay"
    DESK_OPENED = "desk_opened"
    BREADTH = "breadth"
    """One agent standing in for so many charters that no measurement about
    any one of them is attributable. The launch roster's defining condition,
    and the trigger the company fires on itself first."""
