"""Judgement: an agent states a view about a market before the outcome exists.

This package is the answer to the hardest constraint in the brief. **An
agent's judgement cannot be backtested.** Ask a model what it thinks about
BTC in March 2020 and it already knows what happened; every historical
decision it makes is contaminated by hindsight it cannot switch off, and the
resulting number is worthless and convincing. Any design that replays history
and lets agents trade it is measuring memory rather than skill.

So the evidence is forward, and the package is built around four facts that
the ledger can enforce.

**The agent chooses.** Which market, which instrument, which horizon. The
option set is the instruments the company can *resolve* — the ones it holds a
recording of and can fetch again — because a prediction nobody can check is
not a prediction. Nothing inside that set is assigned.

**The prediction is sealed before the outcome exists.** A thesis records the
reference close it was made against, the instant it resolves, and a hash over
every field that matters. The database refuses to change any of them
afterwards, and the seat refuses a thesis whose horizon has already passed at
the moment of sealing — the one way a "forward" prediction could quietly be a
backward one.

**It is scored once, mechanically, against a recording.** When the horizon
expires and a recording covers it, the close at the horizon settles the
proposition and the Brier score is written. A thesis is never rescored.

**Calibration is the measure.** An agent that says 70% and is right 70% of
the time knows something. One that says 90% and is right 55% of the time is
confident and useless, and the record says so within weeks. P&L over a short
window is mostly luck; calibration over hundreds of sealed calls is much harder
to fake.

What runs behind the seat offline is a deterministic stand-in, as with every
other seat in this repository, and every report says so.
"""

from aurelis.judgement.calibration import (
    AgentCalibration,
    Band,
    agent_calibration,
    company_calibration,
)
from aurelis.judgement.resolution import Resolution, resolve_due
from aurelis.judgement.seat import (
    HORIZONS,
    JudgementRefused,
    SealedThesis,
    Seat,
    seat_agent,
)
from aurelis.judgement.tables import Thesis

__all__ = [
    "HORIZONS",
    "AgentCalibration",
    "Band",
    "JudgementRefused",
    "Resolution",
    "SealedThesis",
    "Seat",
    "Thesis",
    "agent_calibration",
    "company_calibration",
    "resolve_due",
    "seat_agent",
]
