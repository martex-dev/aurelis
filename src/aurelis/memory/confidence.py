"""How much the company is entitled to believe a finding.

Confidence here is a **band**, not a number, and it is **derived**, never
stored. Both choices are deliberate.

A number invites arithmetic nobody can defend. "0.72 confidence" reads as a
probability, is not one, and the moment it is stored it starts being averaged,
thresholded and compared across findings that were never commensurable. A band
— NONE, WEAK, MODERATE, STRONG — says what it means and refuses to say more.

Deriving it rather than storing it is what makes the M6 acceptance criterion
possible: *a finding's confidence degrades when an objection opens against it*.
If confidence were a column, degrading it would require somebody to remember to
go and update it, and the one time that mattered would be the time nobody did.
Computed from the record, an objection filed at 3am lowers the band the next
time anyone asks, with no coordination at all.

The rules are caps rather than contributions. Evidence can raise the band;
**anything wrong with the finding lowers it, and the lowest cap wins**. That
asymmetry is the point — it is why accumulating supporting evidence can never
outvote an unresolved critical objection, which is precisely the failure mode
that lets a research organisation talk itself into a bad position.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.meetings.tables import MeetingObjection
from aurelis.meetings.types import ObjectionSeverity, ObjectionStatus
from aurelis.memory.graph import IndependentSupport, KnowledgeGraph
from aurelis.research.states import REPORTABLE_EVIDENCE, Polarity, Verdict
from aurelis.research.tables import Evidence, Finding, Registration, Replication

__all__ = ["Confidence", "ConfidenceBand", "assess", "write_cap_reason"]


class ConfidenceBand(IntEnum):
    """Ordered, so caps compose by taking a minimum.

    ``IntEnum`` because the whole mechanism is "the lowest cap wins", and
    expressing that over an unordered vocabulary would mean a lookup table
    somebody would eventually get wrong.
    """

    NONE = 0
    """The record does not support believing this. Not the same as false."""

    WEAK = 1
    """One line of support, unreplicated, or a live doubt standing against it."""

    MODERATE = 2
    """Independent support, nothing serious outstanding."""

    STRONG = 3
    """Independently supported, replicated with a real variation, unchallenged.
    Reachable, and rare — which is the correct frequency."""

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class Confidence:
    """A band, and every reason it is not higher.

    ``caps`` is the honest part. A reader who sees MODERATE learns little; one
    who sees "MODERATE — capped by OBJ-0004, an open major objection" knows
    exactly what would have to change for it to move.
    """

    finding_ref: str
    band: ConfidenceBand
    caps: tuple[str, ...]
    support: IndependentSupport
    replications: int
    open_objections: int

    @property
    def cap_reason(self) -> str:
        return "; ".join(self.caps)

    def describe(self) -> str:
        head = f"{self.finding_ref}: {self.band.label}"
        return f"{head} — {self.cap_reason}" if self.caps else f"{head} (uncapped)"


def assess(
    session: Session,
    finding: Finding,
    *,
    graph: KnowledgeGraph | None = None,
) -> Confidence:
    """Work out what the record entitles the company to believe.

    Reads only the record: the verdict, the evidence rows at reportable levels,
    the replications that held with a declared variation, the graph's
    independent-support count, and the objections still open. Nothing an agent
    asserted about its own confidence is consulted, because an agent's stated
    confidence is a property of its prose style.
    """
    the_graph = graph or KnowledgeGraph()
    support = the_graph.independent_support(session, finding.hypothesis_ref)

    supporting_evidence = int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(Evidence)
            .where(
                Evidence.finding_ref == finding.ref,
                Evidence.polarity == Polarity.SUPPORTS.value,
                Evidence.kind.in_([kind.value for kind in REPORTABLE_EVIDENCE]),
            )
        ).scalar_one()
    )

    registrations = sa.select(Registration.ref).where(
        Registration.hypothesis_ref == finding.hypothesis_ref
    )
    replications = int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(Replication)
            .where(
                Replication.parent_registration_ref.in_(registrations),
                Replication.outcome == "held",
            )
        ).scalar_one()
    )

    objections = list(
        session.execute(
            sa.select(MeetingObjection).where(
                MeetingObjection.target == finding.hypothesis_ref
            )
        ).scalars()
    )

    caps: list[str] = []
    band = _earned(support, supporting_evidence, replications, caps)
    band = _capped_by_verdict(finding, band, caps)
    band, open_count = _capped_by_objections(objections, band, caps)

    return Confidence(
        finding_ref=finding.ref,
        band=band,
        caps=tuple(caps),
        support=support,
        replications=replications,
        open_objections=open_count,
    )


def _earned(
    support: IndependentSupport,
    supporting_evidence: int,
    replications: int,
    caps: list[str],
) -> ConfidenceBand:
    """The highest band the positive record could justify on its own."""
    if supporting_evidence == 0:
        caps.append("no reportable supporting evidence is recorded")
        return ConfidenceBand.NONE

    if support.independent >= 2 and replications >= 1:
        return ConfidenceBand.STRONG

    if support.independent >= 2:
        caps.append(
            "no replication has held with a declared variation, so this still "
            "rests on the original design"
        )
        return ConfidenceBand.MODERATE

    if support.overcounted_by > 0:
        caps.append(
            f"support is not independent: {support.naive} supporting results "
            f"collapse to {support.independent} once correlation is discounted"
        )
        return ConfidenceBand.WEAK

    if support.independent == 0:
        # Evidence is recorded against the finding, but nothing in the graph
        # links a result to the claim. Reported as the absence it is: the
        # company holds material, and no independent agreement about it.
        caps.append(
            "no result is linked to the hypothesis in the graph, so there is "
            "nothing to judge independence against"
        )
        return ConfidenceBand.WEAK

    caps.append("a single line of support; nothing has independently agreed")
    return ConfidenceBand.WEAK


def _capped_by_verdict(
    finding: Finding, band: ConfidenceBand, caps: list[str]
) -> ConfidenceBand:
    """UNDERPOWERED and INVALID are abstentions, not weak findings.

    Treating an abstention as weak evidence is exactly how confident nothing
    accumulates, so these floor the band regardless of what else is on record.
    """
    if finding.verdict == Verdict.UNDERPOWERED.value:
        caps.append(
            "the verdict is underpowered: the interval cannot distinguish the "
            "claim from nothing, which is a statement about the design and not "
            "evidence in either direction"
        )
        return ConfidenceBand.NONE
    if finding.verdict == Verdict.INVALID.value:
        caps.append("the run did not produce what the registration asked for")
        return ConfidenceBand.NONE
    if finding.verdict == Verdict.REFUTED.value:
        caps.append("the finding is that the claim did not hold")
        return min(band, ConfidenceBand.WEAK)
    if finding.verdict == Verdict.INCONCLUSIVE.value:
        caps.append("a real effect, smaller than the one claimed")
        return min(band, ConfidenceBand.WEAK)
    return band


def _capped_by_objections(
    objections: list[MeetingObjection],
    band: ConfidenceBand,
    caps: list[str],
) -> tuple[ConfidenceBand, int]:
    """The mechanism the M6 acceptance criterion names.

    An objection **that is merely open** lowers the band. It does not have to
    be upheld, or even tested: the company does not get to keep believing
    something at full strength while a stated, unanswered doubt sits against
    it. Resolving the objection — in either direction — lifts the cap, which is
    the incentive the design wants.
    """
    ceiling = band
    open_count = 0

    for objection in sorted(objections, key=lambda row: row.ref):
        if objection.status == ObjectionStatus.UPHELD.value:
            caps.append(f"{objection.ref} was upheld by measurement: {objection.type}")
            ceiling = ConfidenceBand.NONE
            continue

        if objection.status == ObjectionStatus.REJECTED.value:
            continue

        open_count += 1
        if objection.status == ObjectionStatus.UNTESTABLE.value:
            caps.append(
                f"{objection.ref} ({objection.type}) could not be settled by "
                "measurement and stands as an unresolved limitation"
            )
            ceiling = min(ceiling, ConfidenceBand.WEAK)
        elif objection.severity == ObjectionSeverity.CRITICAL.value:
            caps.append(f"{objection.ref} is an open critical {objection.type}")
            ceiling = ConfidenceBand.NONE
        elif objection.severity == ObjectionSeverity.MAJOR.value:
            caps.append(f"{objection.ref} is an open major {objection.type}")
            ceiling = min(ceiling, ConfidenceBand.WEAK)
        else:
            caps.append(f"{objection.ref} is an open minor {objection.type}")
            ceiling = min(ceiling, ConfidenceBand.MODERATE)

    return ceiling, open_count


def write_cap_reason(session: Session, confidence: Confidence) -> None:
    """Record why the band is where it is, on the finding itself.

    The band stays derived; only the *explanation* is persisted, so a reader of
    the raw table sees the reasoning without re-running this module. A stale
    explanation is a cosmetic problem; a stale band would be a correctness one,
    which is why only one of the two is ever stored.
    """
    finding = session.execute(
        sa.select(Finding).where(Finding.ref == confidence.finding_ref)
    ).scalar_one()
    finding.confidence_cap_reason = confidence.cap_reason[:4000]
    session.flush()
