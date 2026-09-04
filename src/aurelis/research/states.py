"""The research vocabulary.

Two distinctions here do most of the work.

**REFUTED and INCONCLUSIVE are terminal successes**, reported with the same
prominence as CONFIRMED. A researcher that correctly kills a bad idea has
produced valuable work, and a corpus that only records what survived is a
corpus that has forgotten what it cost to get there.

**INCONCLUSIVE and UNDERPOWERED are different verdicts**, and collapsing them is
a real error with a measured cost — nullius found the collapse had inflated
every arm's accuracy by four to nine items out of sixty. INCONCLUSIVE is a
statement about the *world*: there is an effect, and it is smaller than the one
claimed. UNDERPOWERED is a statement about the *design*: the interval is too
wide for the data to say anything either way. One is a finding; the other is an
abstention, and treating an abstention as a finding is how confident nothing
accumulates.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "TERMINAL_VERDICTS",
    "ComputedBy",
    "EvidenceKind",
    "HypothesisState",
    "Polarity",
    "RegistrationKind",
    "RunStatus",
    "Verdict",
]


class HypothesisState(StrEnum):
    DRAFT = "draft"
    SCREENED = "screened"
    """Checked against prior art. The company has asked "have we tried this
    before?" before spending anything on it."""

    REGISTERED = "registered"
    """A locked, hashed preregistration exists. Nothing may run before this."""

    DESIGNED = "designed"
    RUNNING = "running"
    ANALYZED = "analyzed"
    CHALLENGED = "challenged"
    REPLICATED = "replicated"
    REVIEWED = "reviewed"

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    UNDERPOWERED = "underpowered"
    SHELVED = "shelved"
    ABANDONED_BUDGET = "abandoned_budget"


TERMINAL_STATES = frozenset(
    {
        HypothesisState.CONFIRMED,
        HypothesisState.REFUTED,
        HypothesisState.INCONCLUSIVE,
        HypothesisState.UNDERPOWERED,
        HypothesisState.SHELVED,
        HypothesisState.ABANDONED_BUDGET,
    }
)


class Verdict(StrEnum):
    """What a run's measurements said about the registered claim."""

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    """A real effect, smaller than claimed. A fact about the world."""

    UNDERPOWERED = "underpowered"
    """The interval is too wide to distinguish the claim from nothing. A fact
    about the design, and never counted as evidence either way."""

    INVALID = "invalid"
    """The run did not produce what the registration asked for. Not a result."""


TERMINAL_VERDICTS = frozenset(
    {Verdict.CONFIRMED, Verdict.REFUTED, Verdict.INCONCLUSIVE, Verdict.UNDERPOWERED}
)


class RegistrationKind(StrEnum):
    """What kind of claim this registration makes.

    The distinction is not bookkeeping. A confirmatory trial spends the
    family's error budget; an exploratory one does not, and may not be reported
    as confirmation of anything. A registration revised after results exist is
    **degraded to exploratory automatically**, which is what stops a
    disappointing confirmatory test from being quietly re-aimed.
    """

    CONFIRMATORY = "confirmatory"
    EXPLORATORY = "exploratory"
    REPLICATION = "replication"
    """Re-tests an existing claim with a declared variation. Spends no error
    budget, because it is not a new bet on the same data."""


class RunStatus(StrEnum):
    COMPLETED = "completed"
    INFRA_FAILURE = "infra_failure"
    """A timeout, a dropped connection. May be retried."""

    SCIENTIFIC_FAILURE = "scientific_failure"
    """The computation ran and could not produce a valid answer. **Never
    retried** -- it is a research object in its own right, and retrying it
    until it succeeds is how a null result becomes a discovery."""

    TIMEOUT = "timeout"
    REFUSED = "refused"


class ComputedBy(StrEnum):
    """Who produced a measurement.

    A closed set with no agent in it. This is the enum that makes "no agent
    writes a number" a database constraint rather than a principle.
    """

    ENGINE = "engine"
    CUSTODIAN = "custodian"
    """Sealed out-of-sample metrics only, released against a counted budget."""


class EvidenceKind(StrEnum):
    """The assertion ladder. Promotion between levels is illegal."""

    OBSERVED_FACT = "observed_fact"
    """Written only from an artifact produced by an engine."""

    SOURCED_CLAIM = "sourced_claim"
    """Has a resolvable source and a stored verbatim passage."""

    INFERRED_CLAIM = "inferred_claim"
    """Has at least one parent evidence row."""

    HYPOTHESIS = "hypothesis"
    """Never evidence for anything."""

    SPECULATION = "speculation"
    """Excluded from every report and every metric. Allowed to exist so that
    it can be marked, rather than laundered into something stronger."""


REPORTABLE_EVIDENCE = frozenset(
    {EvidenceKind.OBSERVED_FACT, EvidenceKind.SOURCED_CLAIM, EvidenceKind.INFERRED_CLAIM}
)


class Polarity(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


HYPOTHESIS_TRANSITIONS: dict[HypothesisState, frozenset[HypothesisState]] = {
    HypothesisState.DRAFT: frozenset(
        {HypothesisState.SCREENED, HypothesisState.SHELVED}
    ),
    HypothesisState.SCREENED: frozenset(
        {HypothesisState.REGISTERED, HypothesisState.SHELVED}
    ),
    HypothesisState.REGISTERED: frozenset(
        {HypothesisState.DESIGNED, HypothesisState.SHELVED}
    ),
    HypothesisState.DESIGNED: frozenset(
        {HypothesisState.RUNNING, HypothesisState.ABANDONED_BUDGET}
    ),
    HypothesisState.RUNNING: frozenset(
        {HypothesisState.ANALYZED, HypothesisState.ABANDONED_BUDGET}
    ),
    HypothesisState.ANALYZED: frozenset(
        {
            HypothesisState.CHALLENGED,
            HypothesisState.CONFIRMED,
            HypothesisState.REFUTED,
            HypothesisState.INCONCLUSIVE,
            HypothesisState.UNDERPOWERED,
        }
    ),
    HypothesisState.CHALLENGED: frozenset(
        {
            HypothesisState.REPLICATED,
            HypothesisState.REFUTED,
            HypothesisState.INCONCLUSIVE,
            HypothesisState.UNDERPOWERED,
        }
    ),
    HypothesisState.REPLICATED: frozenset(
        {HypothesisState.REVIEWED, HypothesisState.REFUTED}
    ),
    HypothesisState.REVIEWED: frozenset(
        {
            HypothesisState.CONFIRMED,
            HypothesisState.REFUTED,
            HypothesisState.INCONCLUSIVE,
            HypothesisState.UNDERPOWERED,
        }
    ),
}


def may_transition(current: str, target: str) -> bool:
    try:
        return HypothesisState(target) in HYPOTHESIS_TRANSITIONS[HypothesisState(current)]
    except (ValueError, KeyError):
        return False
