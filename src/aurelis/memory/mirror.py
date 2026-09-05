"""Putting the company's own work into the graph.

The research lifecycle writes hypotheses, findings and replications. The graph
answers questions about how they relate. Something has to connect the two, and
it is deliberately *not* the research layer reaching into memory: research
knows nothing about the graph, so a change to how the graph works can never
break a run.

So the mirror reads the research record and derives the graph from it. It is a
projection, and it has the properties a projection should have — idempotent,
re-runnable, and adding nothing that is not already in the record:

* a finding whose verdict CONFIRMED its hypothesis becomes a ``SUPPORTS`` edge;
* one that REFUTED it becomes ``CONTRADICTS``;
* a replication that held becomes a second, separate supporter — which is what
  makes STRONG confidence reachable at all, and only by the route it should be;
* a derived hypothesis ``DEPENDS_ON`` the one it came from.

Everything else the graph could hold — that two results are correlated, that
one finding invalidates another — is a *judgement*, and judgements are entered
by whoever makes them, with their name on the edge. The mirror draws only what
the record already states, because an edge the system inferred would carry the
same weight in the independent-support count as one somebody defended.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.memory.graph import EdgeKind, KnowledgeGraph, NodeKind
from aurelis.platform.ledger.ledger import Ledger
from aurelis.research.states import Verdict
from aurelis.research.tables import Finding, Hypothesis, Registration, Replication

__all__ = ["MirrorReport", "mirror_research"]

_MIRROR = "mirror"
"""The author recorded on every derived edge.

A distinct name so that ``created_by`` separates what the record implied from
what a person or an agent asserted. An edge signed by the mirror can be
regenerated; one signed by an agent cannot.
"""


@dataclass(frozen=True, slots=True)
class MirrorReport:
    nodes: int
    edges: int
    hypotheses: int
    findings: int
    replications: int

    def describe(self) -> str:
        return (
            f"mirrored {self.hypotheses} hypotheses, {self.findings} findings "
            f"and {self.replications} replications into the graph "
            f"({self.nodes} new node(s), {self.edges} new edge(s))"
        )


def mirror_research(
    session: Session,
    *,
    graph: KnowledgeGraph | None = None,
    ledger: Ledger | None = None,
    clock: Clock | None = None,
    at: dt.datetime | None = None,
) -> MirrorReport:
    """Project the research record onto the graph. Idempotent."""
    the_clock = clock or SystemClock()
    moment = at or the_clock.now()
    the_graph = graph or KnowledgeGraph(the_clock)

    before_nodes, before_edges = _counts(session)

    hypotheses = list(session.execute(sa.select(Hypothesis)).scalars())
    for hypothesis in hypotheses:
        the_graph.add_node(
            session,
            node_id=hypothesis.ref,
            kind=NodeKind.HYPOTHESIS,
            label=hypothesis.claim,
            family=hypothesis.family,
            desk=hypothesis.desk,
            payload={"state": hypothesis.state, "author": hypothesis.author},
            at=moment,
        )

    for hypothesis in hypotheses:
        if hypothesis.parent_ref and the_graph.node(session, hypothesis.parent_ref):
            the_graph.relate(
                session,
                source=hypothesis.ref,
                target=hypothesis.parent_ref,
                kind=EdgeKind.DEPENDS_ON,
                created_by=_MIRROR,
                note=f"{hypothesis.derivation} of its parent, per the record",
                at=moment,
            )

    findings = list(session.execute(sa.select(Finding)).scalars())
    for finding in findings:
        if the_graph.node(session, finding.hypothesis_ref) is None:
            continue
        the_graph.add_node(
            session,
            node_id=finding.ref,
            kind=NodeKind.FINDING,
            label=finding.statement,
            payload={"verdict": finding.verdict, "run_ref": finding.run_ref},
            at=moment,
        )
        kind = _edge_for(finding.verdict)
        if kind is None:
            # UNDERPOWERED and INVALID are abstentions. Linking one as support
            # OR as contradiction would make an absence of information count
            # as information, which is the error the verdict vocabulary exists
            # to prevent.
            continue
        the_graph.relate(
            session,
            source=finding.ref,
            target=finding.hypothesis_ref,
            kind=kind,
            created_by=_MIRROR,
            evidence_ref=finding.run_ref,
            note=f"the finding's verdict was {finding.verdict}",
            at=moment,
        )

    replications = _mirror_replications(session, the_graph, moment)

    after_nodes, after_edges = _counts(session)
    report = MirrorReport(
        nodes=after_nodes - before_nodes,
        edges=after_edges - before_edges,
        hypotheses=len(hypotheses),
        findings=len(findings),
        replications=replications,
    )
    if ledger is not None and (report.nodes or report.edges):
        ledger.append(
            session,
            kind=EventKind.KNOWLEDGE_LINKED,
            actor=Actor.SYSTEM,
            subject="research",
            payload={
                "new_nodes": report.nodes,
                "new_edges": report.edges,
                "hypotheses": report.hypotheses,
                "findings": report.findings,
                "replications": report.replications,
            },
            at=moment,
        )
    return report


def _mirror_replications(
    session: Session, graph: KnowledgeGraph, moment: dt.datetime
) -> int:
    """A replication that held is a *separate* supporter.

    Separate because it varied something and the claim survived anyway. That is
    the only route to STRONG confidence, and it is the right one: a result
    re-run unchanged is the same observation twice, which the correlation
    discount would collapse in any case.
    """
    rows = list(
        session.execute(
            sa.select(Replication, Registration.hypothesis_ref).join(
                Registration,
                Registration.ref == Replication.parent_registration_ref,
            )
        ).all()
    )
    for replication, hypothesis_ref in rows:
        if graph.node(session, hypothesis_ref) is None:
            continue
        graph.add_node(
            session,
            node_id=replication.ref,
            kind=NodeKind.TRIAL,
            label=f"replication varying {replication.varied}",
            payload={"outcome": replication.outcome, "varied": replication.varied},
            at=moment,
        )
        kind = {
            "held": EdgeKind.SUPPORTS,
            "broke": EdgeKind.CONTRADICTS,
        }.get(replication.outcome)
        if kind is None:
            continue
        graph.relate(
            session,
            source=replication.ref,
            target=hypothesis_ref,
            kind=kind,
            created_by=_MIRROR,
            evidence_ref=replication.run_ref,
            note=f"replication varying {replication.varied} {replication.outcome}",
            at=moment,
        )
    return len(rows)


def _edge_for(verdict: str) -> EdgeKind | None:
    if verdict == Verdict.CONFIRMED.value:
        return EdgeKind.SUPPORTS
    if verdict in (Verdict.REFUTED.value, Verdict.INCONCLUSIVE.value):
        return EdgeKind.CONTRADICTS
    return None


def _counts(session: Session) -> tuple[int, int]:
    from aurelis.memory.tables import KnowledgeEdge, KnowledgeNode

    nodes = int(
        session.execute(
            sa.select(sa.func.count()).select_from(KnowledgeNode)
        ).scalar_one()
    )
    edges = int(
        session.execute(
            sa.select(sa.func.count()).select_from(KnowledgeEdge)
        ).scalar_one()
    )
    return nodes, edges
