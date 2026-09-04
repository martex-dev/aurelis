"""Quantitative Research.

At M2 this is questions and triage: reading someone else's work, checking it
independently, and deciding whether it earns a project. The research
lifecycle -- hypotheses, preregistration, experiments, findings -- arrives at
M4, when there is a Registrar to lock a spec and a trigger to refuse a run
that precedes its registration.
"""

from aurelis.research.triage import QUESTION_TASK, TRIAGE_TASK, raise_question, triage_question

__all__ = ["QUESTION_TASK", "TRIAGE_TASK", "raise_question", "triage_question"]
