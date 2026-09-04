"""Meetings: how the company thinks together.

Agents brainstorm, argue, present evidence, change each other's minds and
decide. The transcript is kept in full because reading why the company
believes something is one of the things Mission Control exists for.

The mechanisms that keep a meeting from becoming theatre are all here:
private forecasts recorded before anyone speaks, a validator that refuses any
figure a speaker was not shown, objections that carry an executable test the
Chair actually dispatches, dissent stored permanently on the decision, and a
productivity metric that names a meeting which produced nothing.
"""

from aurelis.meetings.chair import Chair, MeetingOutcome, ProposedAction, ProposedObjection
from aurelis.meetings.challenge import TestOutcome, TestSpec, parse_spec
from aurelis.meetings.forecasts import UNINFORMATIVE_BRIER, Calibration, ForecastScorer
from aurelis.meetings.protocol import PROTOCOLS, Protocol, protocol_for
from aurelis.meetings.tables import (
    ActionItem,
    Decision,
    Forecast,
    Meeting,
    MeetingObjection,
    MeetingParticipant,
    MeetingTurn,
)
from aurelis.meetings.types import (
    Attendance,
    MeetingStatus,
    MeetingType,
    ObjectionSeverity,
    ObjectionStatus,
    ObjectionType,
    Phase,
    Stance,
    TurnKind,
)

__all__ = [
    "PROTOCOLS",
    "UNINFORMATIVE_BRIER",
    "ActionItem",
    "Attendance",
    "Calibration",
    "Chair",
    "Decision",
    "Forecast",
    "ForecastScorer",
    "Meeting",
    "MeetingObjection",
    "MeetingOutcome",
    "MeetingParticipant",
    "MeetingStatus",
    "MeetingTurn",
    "MeetingType",
    "ObjectionSeverity",
    "ObjectionStatus",
    "ObjectionType",
    "Phase",
    "ProposedAction",
    "ProposedObjection",
    "Protocol",
    "Stance",
    "TestOutcome",
    "TestSpec",
    "TurnKind",
    "parse_spec",
    "protocol_for",
]
