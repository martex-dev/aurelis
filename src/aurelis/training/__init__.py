"""Training scenarios: measuring agents and org changes (ADR-0005).

The company must be able to say whether a hire, a revision or a structural
change made it better. Real research cannot answer that quickly -- the feedback
loop is months long, a failure may have been an edge that regime-shifted, and
grading one agent's prose with another agent is circular.

So the company is scored on worlds where the answer is known: planted defects,
planted premia, and a third of the catalogue with nothing in it at all. What is
scored is a **procedure** -- the checks a charter issues -- run against one draw
of each world, while the answer is settled by twenty-four draws no experiment
would be allowed.

Every score here is **institutional competence, not market truth**. An agent
that catches planted survivorship may still be badly calibrated on a real
market, and every report says which it is.
"""

from __future__ import annotations

from aurelis.training.critique import CRITIC_SEED, Critique, apply_playbook
from aurelis.training.onboarding import (
    STANDARD,
    Onboarding,
    Standard,
    TrainingOutcome,
)
from aurelis.training.playbook import (
    INCUMBENT,
    SPECIALTIES,
    Check,
    Playbook,
    playbook_for,
    specialty_of,
)
from aurelis.training.regression import RegressionVerdict, gate
from aurelis.training.scoring import Mark, Scorecard, mark, tally
from aurelis.training.suite import SuiteResult, TrainingSuite
from aurelis.training.tables import ScenarioMark, TrainingRun, TrainingVerdict

__all__ = [
    "CRITIC_SEED",
    "INCUMBENT",
    "SPECIALTIES",
    "STANDARD",
    "Check",
    "Critique",
    "Mark",
    "Onboarding",
    "Playbook",
    "RegressionVerdict",
    "ScenarioMark",
    "Scorecard",
    "Standard",
    "SuiteResult",
    "TrainingOutcome",
    "TrainingRun",
    "TrainingSuite",
    "TrainingVerdict",
    "apply_playbook",
    "gate",
    "mark",
    "playbook_for",
    "specialty_of",
    "tally",
]
