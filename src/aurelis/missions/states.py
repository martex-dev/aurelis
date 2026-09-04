"""Mission and project state machines.

Two rules carry the weight.

**A mission cannot leave PLANNING without a kickoff**, and cannot reach CLOSED
without a retrospective. Meeting at the start and at the end is a property of
the system rather than a habit somebody remembers — enforced here, on the
transition, not requested in a prompt.

**BUDGET_EXHAUSTED is a terminal success, not an error.** A company that could
not afford to answer a question has learned something about the question, and
the record should say so rather than showing a mission that mysteriously
stopped.

At M2 the kickoff gate is satisfied by an operator-recorded plan; at M3 a
Kickoff *meeting* produces the same artifact. The gate does not change — only
who is able to satisfy it.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "MISSION_TRANSITIONS",
    "PROJECT_TRANSITIONS",
    "TERMINAL_MISSION_STATES",
    "TERMINAL_PROJECT_STATES",
    "KickoffKind",
    "MissionState",
    "ProjectState",
    "may_transition",
]


class MissionState(StrEnum):
    PROPOSED = "proposed"
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    REVIEWING = "reviewing"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ProjectState(StrEnum):
    PROPOSED = "proposed"
    PLANNING = "planning"
    ACTIVE = "active"
    REVIEWING = "reviewing"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class KickoffKind(StrEnum):
    """What satisfied the kickoff gate.

    ``MEETING`` becomes the norm at M3. ``OPERATOR`` is a human doing the
    kickoff's job — writing the plan — and is reported by ``aurelis doctor``
    so it never becomes an invisible habit.
    """

    MEETING = "meeting"
    OPERATOR = "operator"


MISSION_TRANSITIONS: dict[MissionState, frozenset[MissionState]] = {
    MissionState.PROPOSED: frozenset({MissionState.PLANNING, MissionState.CANCELLED}),
    MissionState.PLANNING: frozenset({MissionState.ACTIVE, MissionState.CANCELLED}),
    MissionState.ACTIVE: frozenset(
        {
            MissionState.PAUSED,
            MissionState.REVIEWING,
            MissionState.CANCELLED,
            MissionState.BUDGET_EXHAUSTED,
        }
    ),
    MissionState.PAUSED: frozenset({MissionState.ACTIVE, MissionState.CANCELLED}),
    MissionState.REVIEWING: frozenset({MissionState.CLOSED, MissionState.ACTIVE}),
    MissionState.CLOSED: frozenset(),
    MissionState.CANCELLED: frozenset(),
    MissionState.BUDGET_EXHAUSTED: frozenset({MissionState.REVIEWING}),
}
"""``REVIEWING → ACTIVE`` is deliberate: a retrospective that uncovers unfinished
work should be able to reopen the mission rather than force a new one that
loses the history."""

PROJECT_TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = {
    ProjectState.PROPOSED: frozenset({ProjectState.PLANNING, ProjectState.CANCELLED}),
    ProjectState.PLANNING: frozenset({ProjectState.ACTIVE, ProjectState.CANCELLED}),
    ProjectState.ACTIVE: frozenset(
        {ProjectState.REVIEWING, ProjectState.CANCELLED, ProjectState.BUDGET_EXHAUSTED}
    ),
    ProjectState.REVIEWING: frozenset({ProjectState.CLOSED, ProjectState.ACTIVE}),
    ProjectState.CLOSED: frozenset(),
    ProjectState.CANCELLED: frozenset(),
    ProjectState.BUDGET_EXHAUSTED: frozenset({ProjectState.REVIEWING}),
}

TERMINAL_MISSION_STATES = frozenset({MissionState.CLOSED, MissionState.CANCELLED})
TERMINAL_PROJECT_STATES = frozenset({ProjectState.CLOSED, ProjectState.CANCELLED})


def may_transition(current: str, target: str, *, project: bool = False) -> bool:
    """Whether ``current -> target`` is a legal move.

    An unknown state returns False rather than raising: the caller is asking a
    question, and "no" is the right answer for a value the machine has never
    heard of.
    """
    try:
        if project:
            return ProjectState(target) in PROJECT_TRANSITIONS[ProjectState(current)]
        return MissionState(target) in MISSION_TRANSITIONS[MissionState(current)]
    except (ValueError, KeyError):
        return False
