"""Taking the standard, and answering it.

The company checks itself against eleven conditions it declared in advance, and
returns one of two words. There is no third: a company that could report
"nearly ready" would eventually report it about everything.

**Only a `ready` escalates.** A `not_yet` is written down and nobody is
interrupted, because a system that pinged its owner every time it looked would
train them to stop reading. The ask, when it comes, has to be rare enough to be
worth opening.

What an honest first answer looks like
--------------------------------------

.. code-block:: text

    NOT YET   3 of 10 met, and 2 of the 7 unmet are blocked

    blocked   live_data          no desk has a wired feed
              replicated         the replications table has no writer

The blocked ones are the useful half. *Unmet* is a research result — go and do
better. *Blocked* means no amount of research would help, because the machinery
to produce the evidence does not exist. Separating them turns the standard from
a scoreboard into the company's own answer to "what should we build next", and
it is derived from the declared bar rather than from anybody's opinion.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.mandate.standard import STANDARD, Criterion, digest
from aurelis.mandate.tables import MandateAssessment
from aurelis.platform.db.refs import allocate_ref

__all__ = ["Finding", "MandateOutcome", "assess", "history"]

READY = "ready"
NOT_YET = "not_yet"


@dataclass(frozen=True, slots=True)
class Finding:
    """One criterion, and the reading that settled it."""

    criterion: Criterion
    met: bool
    reading: str

    @property
    def blocked(self) -> bool:
        """Unmet, and unmeetable by research alone."""
        return not self.met and self.criterion.blocked

    def describe(self) -> str:
        mark = "MET " if self.met else ("BLOCKED" if self.blocked else "unmet")
        return f"{mark:8} {self.criterion.key:20} {self.reading}"

    def as_payload(self) -> dict[str, Any]:
        return {
            "key": self.criterion.key,
            "asks": self.criterion.asks,
            "met": self.met,
            "reading": self.reading,
            "blocked_by": self.criterion.blocked_by if self.blocked else "",
        }


@dataclass(frozen=True, slots=True)
class MandateOutcome:
    """What the company concluded about itself, and whether it asked."""

    ref: str
    standard_digest: str
    findings: tuple[Finding, ...]
    escalated_to: str | None
    assessed_at: dt.datetime
    previous_digest: str | None = None
    """The digest of the assessment before this one, when there was one and it
    differed. Present means the bar moved between the two."""

    @property
    def met(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.met)

    @property
    def unmet(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if not f.met)

    @property
    def blocked(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.blocked)

    @property
    def ready(self) -> bool:
        return not self.unmet

    @property
    def verdict(self) -> str:
        return READY if self.ready else NOT_YET

    @property
    def standard_changed(self) -> bool:
        return self.previous_digest is not None

    def describe(self) -> str:
        if self.ready:
            return (
                f"{self.ref}: READY — all {len(self.findings)} conditions met. "
                f"Escalated to {self.escalated_to}."
            )
        return (
            f"{self.ref}: NOT YET — {len(self.met)} of {len(self.findings)} met, "
            f"and {len(self.blocked)} of the {len(self.unmet)} unmet are blocked"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "verdict": self.verdict,
            "standard_digest": self.standard_digest,
            "standard_changed": self.standard_changed,
            "previous_digest": self.previous_digest,
            "criteria": len(self.findings),
            "met": len(self.met),
            "blocked": len(self.blocked),
            "findings": [f.as_payload() for f in self.findings],
            "escalated_to": self.escalated_to,
            "note": (
                "A not_yet is recorded and nobody is interrupted. Only a ready "
                "escalates, because an ask that arrives often is an ask nobody "
                "opens."
            ),
        }


def assess(
    runtime: Any, *, escalate_to: str = "OPERATOR", at: dt.datetime | None = None
) -> MandateOutcome:
    """Check the company against its own standard and record the answer.

    Writes a row whichever way it goes. The refusals are the point: a company
    that kept only the assessment that passed could not show the bar had ever
    held, and the bar holding is the only reason to believe the pass.
    """
    moment = at or runtime.clock.now()
    current = digest()

    with runtime.database.session() as session:
        findings = tuple(_take(session, criterion) for criterion in STANDARD)
        previous = _previous_digest(session, current)
        ready = all(finding.met for finding in findings)
        ref = allocate_ref(session, RefKind.MANDATE)

        session.add(
            MandateAssessment(
                assessment_id=uuid7(),
                ref=ref,
                standard_digest=current,
                criteria=len(findings),
                met=sum(1 for f in findings if f.met),
                blocked=sum(1 for f in findings if f.blocked),
                verdict=READY if ready else NOT_YET,
                findings={"criteria": [f.as_payload() for f in findings]},
                escalated_to=escalate_to if ready else None,
                assessed_at=moment,
            )
        )
        session.flush()

        runtime.ledger.append(
            session,
            kind=EventKind.MANDATE_ASSESSED,
            actor=Actor.SYSTEM,
            subject=ref,
            payload={
                "verdict": READY if ready else NOT_YET,
                "standard_digest": current[:16],
                "standard_changed": previous is not None,
                "met": sum(1 for f in findings if f.met),
                "criteria": len(findings),
                "blocked": [f.criterion.key for f in findings if f.blocked],
                "unmet": [f.criterion.key for f in findings if not f.met],
                "escalated_to": escalate_to if ready else None,
            },
            at=moment,
        )

    return MandateOutcome(
        ref=ref,
        standard_digest=current,
        findings=findings,
        escalated_to=escalate_to if ready else None,
        assessed_at=moment,
        previous_digest=previous,
    )


def _take(session: Session, criterion: Criterion) -> Finding:
    """Run one check, and let a broken check fail loudly rather than pass.

    An exception here is a bug in the standard, not evidence about the company.
    Swallowing it into ``met=False`` would hide a broken bar as a strict one,
    and the strictness would be an accident.
    """
    met, reading = criterion.check(session)
    return Finding(criterion=criterion, met=met, reading=reading)


def _previous_digest(session: Session, current: str) -> str | None:
    """The last assessment's digest, if it differed from today's.

    ``None`` when there is no history or the bar has not moved. A value means
    somebody changed the standard between two assessments, which is the one
    thing a reader must not have to go looking for.
    """
    row = session.execute(
        sa.select(MandateAssessment.standard_digest)
        .order_by(MandateAssessment.assessed_at.desc(), MandateAssessment.ref.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None or str(row) == current:
        return None
    return str(row)


def history(session: Session, limit: int = 20) -> list[MandateAssessment]:
    """Every time the company asked itself, newest first."""
    return list(
        session.execute(
            sa.select(MandateAssessment)
            .order_by(MandateAssessment.assessed_at.desc(), MandateAssessment.ref.desc())
            .limit(limit)
        ).scalars()
    )
