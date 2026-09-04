"""The research lifecycle: claim, preregistration, run, verdict.

Every number comes from an engine. Every verdict comes from a pure function
that sees only the criteria registered before the run existed. The researcher
contributes the claim, the design and the interpretation, and never the
measurement or the verdict.
"""

from aurelis.research.lifecycle import Research, ResearchOutcome
from aurelis.research.states import (
    ComputedBy,
    EvidenceKind,
    HypothesisState,
    Polarity,
    RegistrationKind,
    RunStatus,
    Verdict,
    may_transition,
)
from aurelis.research.tables import (
    Evidence,
    Experiment,
    Finding,
    Hypothesis,
    Registration,
    Replication,
    Result,
    Run,
)
from aurelis.research.triage import QUESTION_TASK, TRIAGE_TASK, raise_question, triage_question
from aurelis.research.triggers import (
    expected_research_trigger_names,
    install_research_invariants,
    verify_research_invariants,
)
from aurelis.research.verdict import Criterion, VerdictReport, derive_verdict, parse_criteria

__all__ = [
    "QUESTION_TASK",
    "TRIAGE_TASK",
    "ComputedBy",
    "Criterion",
    "Evidence",
    "EvidenceKind",
    "Experiment",
    "Finding",
    "Hypothesis",
    "HypothesisState",
    "Polarity",
    "Registration",
    "RegistrationKind",
    "Replication",
    "Research",
    "ResearchOutcome",
    "Result",
    "Run",
    "RunStatus",
    "Verdict",
    "VerdictReport",
    "derive_verdict",
    "expected_research_trigger_names",
    "install_research_invariants",
    "may_transition",
    "parse_criteria",
    "raise_question",
    "triage_question",
    "verify_research_invariants",
]
