"""Aurelis exceptions.

Split along one axis that matters operationally: whether the condition is a
**bug** or a **recorded outcome of the company's own rules**.

``IntegrityViolation`` and its subclasses mean the system stopped something
from happening — an agent tried to write outside its scope, a run tried to
precede its registration. Those are successes of the design, and they are
recorded, not swallowed.

``BudgetExhausted`` is not raised at all in normal operation: the queue records
a refusal and returns it. The exception exists for callers that genuinely
cannot proceed.
"""

from __future__ import annotations

__all__ = [
    "AurelisError",
    "BudgetExhausted",
    "ConfigurationError",
    "IntegrityViolation",
    "LedgerTampered",
    "PermissionDenied",
    "ProviderUnavailable",
]


class AurelisError(Exception):
    """Base for everything this project raises deliberately."""


class ConfigurationError(AurelisError):
    """The system is misconfigured and cannot start."""


class IntegrityViolation(AurelisError):
    """An invariant of the institution was violated.

    Raised where a database constraint cannot reach — never as a substitute
    for one. If a rule can be a trigger, it is a trigger, because an invariant
    only our own code enforces is a convention.
    """


class LedgerTampered(IntegrityViolation):
    """The event chain does not verify.

    Carries the sequence number where verification failed, because "the ledger
    is broken" is not actionable and "the chain breaks at seq 4,182" is.
    """

    def __init__(self, seq: int, detail: str) -> None:
        super().__init__(f"ledger chain broken at seq {seq}: {detail}")
        self.seq = seq
        self.detail = detail


class PermissionDenied(IntegrityViolation):
    """An actor attempted something outside its resolved scope."""

    def __init__(self, actor: str, action: str, subject: str) -> None:
        super().__init__(f"{actor} may not {action} on {subject}")
        self.actor = actor
        self.action = action
        self.subject = subject


class BudgetExhausted(AurelisError):
    """An allowance would be exceeded.

    Names the level that bound, so the message says which knob to turn.
    """

    def __init__(self, scope: str, scope_id: str, remaining: str, requested: str) -> None:
        super().__init__(
            f"{scope} {scope_id} has {remaining} left and {requested} was requested"
        )
        self.scope = scope
        self.scope_id = scope_id
        self.remaining = remaining
        self.requested = requested


class ProviderUnavailable(AurelisError):
    """A model provider is not installed, not configured, or not reachable."""
