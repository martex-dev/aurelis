"""Missions, projects and tasks: how a company-scale objective decomposes.

Three levels, two enforced gates. A mission cannot start work without a
kickoff and cannot close without a retrospective -- meeting at the start and
the end is a property of the state machine rather than a habit.

Progress is computed from task outcomes and reports failures alongside
successes. Nothing here can produce a single reassuring percentage.
"""

from aurelis.missions.missions import Missions, Progress
from aurelis.missions.states import (
    KickoffKind,
    MissionState,
    ProjectState,
    may_transition,
)
from aurelis.missions.tables import Kickoff, Mission, Project, Retrospective, WorkItem

__all__ = [
    "Kickoff",
    "KickoffKind",
    "Mission",
    "MissionState",
    "Missions",
    "Progress",
    "Project",
    "ProjectState",
    "Retrospective",
    "WorkItem",
    "may_transition",
]
