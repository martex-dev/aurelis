"""Risk: an authority, not a reviewer.

Independence here is structural rather than cultural. Nothing reaches execution
without passing through :class:`~aurelis.risk.authority.Risk`, because
:meth:`~aurelis.risk.authority.Risk.approve` takes no exposure argument — it
reads the permitted size off the assessment — and because a database trigger
refuses an approval whose assessment belongs to a different proposal.

Every assessment is written, ``ALLOW`` included. An organisation that recorded
only its interventions could not tell a trade Risk examined and permitted from
one Risk never saw, and those are exactly the two cases an auditor needs to
separate.

The kill latch is one-way. No function in this package clears one: a latch a
program can release is a pause, and the value of a latch is that a person has
to understand what died before anything resumes.
"""

from aurelis.risk.authority import AppliedLimit, Risk
from aurelis.risk.tables import (
    KillLatch,
    RiskAssessment,
    RiskLimit,
    TradeApproval,
    TradeProposal,
)

__all__ = [
    "AppliedLimit",
    "KillLatch",
    "Risk",
    "RiskAssessment",
    "RiskLimit",
    "TradeApproval",
    "TradeProposal",
]
