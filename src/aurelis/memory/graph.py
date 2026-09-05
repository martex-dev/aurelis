"""The knowledge graph.

A corpus of a few hundred trials has a problem no individual document solves:
nobody can hold in their head which conclusions lean on which other
conclusions. When a result is questioned, the load-bearing question is *what
else did we conclude that assumed this was sound?* — and answering it by
re-reading twenty documents is how a corpus quietly rots.

The graph answers three questions and **deliberately refuses more**:

1. What does this rest on? (ancestors)
2. What breaks if it turns out to be wrong? (descendants)
3. Is this claim's support actually independent?

The third is the one with teeth, and it is here because this failure mode is
not hypothetical. martex-quant's own corpus made the error twice: H12 nearly
justified a combined book on a correlation of 0.35 that was really 0.77, and
H59 produced two "inconsistent" cells that looked like confirmation but
correlated at 0.821 — one event, observed twice.

So :func:`independent_support` does not count supporting nodes. It counts
them, **collapses any joined by a correlation above the threshold**, and
reports what it discounted rather than silently returning a smaller number.

What this module does not do, on purpose: it assigns no confidence scores,
computes no aggregate "strength of evidence", and promotes nothing. A graph
that scored its own nodes would invite a reader to trust the score instead of
the sources. Edges are recorded facts with citations; weighing them is
somebody's job, not the graph's.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import uuid7
from aurelis.memory.tables import KnowledgeEdge, KnowledgeNode

__all__ = [
    "CORRELATION_THRESHOLD",
    "EdgeKind",
    "IndependentSupport",
    "KnowledgeGraph",
    "NodeKind",
]

CORRELATION_THRESHOLD = Decimal("0.7")
"""Above this, two supporting nodes are treated as one observation.

A judgement call, stated here rather than buried. H12's true correlation was
0.77 and H59's was 0.821; both sat above this line and both were counted as
independent at the time. The threshold is deliberately visible so it can be
argued with.
"""


class NodeKind(StrEnum):
    HYPOTHESIS = "hypothesis"
    FINDING = "finding"
    META_FINDING = "meta_finding"
    """A conclusion drawn from other conclusions. The kind most at risk of
    resting on support that is not independent."""

    STRATEGY = "strategy"
    OBSERVATION = "observation"
    LESSON = "lesson"
    DECISION = "decision"
    TRIAL = "trial"
    LEAD = "lead"
    """An anomaly worth looking at. **Never a finding**, whatever it looks
    like — leads that quietly became findings are how a corpus rots."""


class EdgeKind(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DEPENDS_ON = "depends_on"
    SUPERSEDES = "supersedes"
    INSPIRED_BY = "inspired_by"
    REPLICATES = "replicates"
    INVALIDATES = "invalidates"
    CORRELATED_WITH = "correlated_with"
    """Two nodes measuring substantially the same underlying event. The weight
    is the measured correlation, and it is what stops repeated observations of
    one event from counting as replication."""


@dataclass(frozen=True, slots=True)
class IndependentSupport:
    """How much genuinely independent support a claim has.

    ``discounted`` is reported alongside the count, never folded into it. A
    reader who is told "three supporting results, two of which are the same
    observation" can weigh that; one told "two" cannot.
    """

    node_id: str
    supporting: tuple[str, ...]
    independent: int
    discounted: tuple[tuple[str, str, Decimal], ...]
    contradicting: tuple[str, ...]

    @property
    def naive(self) -> int:
        """What counting supporters without checking would have said."""
        return len(self.supporting)

    @property
    def overcounted_by(self) -> int:
        return self.naive - self.independent

    def describe(self) -> str:
        if not self.supporting:
            return f"{self.node_id}: no supporting evidence recorded"
        base = f"{self.independent} independent of {self.naive} supporting"
        if self.discounted:
            pairs = "; ".join(
                f"{a} and {b} correlate at {w}" for a, b, w in self.discounted
            )
            base += f" — discounted because {pairs}"
        if self.contradicting:
            base += f"; {len(self.contradicting)} contradicting"
        return f"{self.node_id}: {base}"


class KnowledgeGraph:
    """Records relationships and answers the three questions."""

    __slots__ = ("_clock",)

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()

    # ---------------------------------------------------------------- write

    def add_node(
        self,
        session: Session,
        *,
        node_id: str,
        kind: NodeKind,
        label: str,
        family: str | None = None,
        desk: str | None = None,
        origin: str = "aurelis",
        payload: dict[str, Any] | None = None,
        at: dt.datetime | None = None,
    ) -> KnowledgeNode:
        """Add a node, or return the one already there. Idempotent."""
        existing = session.get(KnowledgeNode, node_id)
        if existing is not None:
            return existing
        node = KnowledgeNode(
            node_id=node_id,
            kind=kind.value,
            label=label[:2000],
            family=family,
            desk=desk,
            origin=origin,
            payload=dict(payload or {}),
            created_at=at or self._clock.now(),
        )
        session.add(node)
        session.flush()
        return node

    def relate(
        self,
        session: Session,
        *,
        source: str,
        target: str,
        kind: EdgeKind,
        created_by: str,
        weight: Decimal | None = None,
        evidence_ref: str | None = None,
        note: str = "",
        at: dt.datetime | None = None,
    ) -> KnowledgeEdge:
        """Record a relationship between two existing nodes.

        Both endpoints must already exist. An edge to a node nobody created
        would let the graph assert a relationship with something that does not
        correspond to anything in the record.
        """
        for endpoint in (source, target):
            if session.get(KnowledgeNode, endpoint) is None:
                raise IntegrityViolation(
                    f"cannot relate to {endpoint!r}: no such node. Edges point "
                    "at things that exist, or the graph is asserting "
                    "relationships with nothing."
                )
        if kind is EdgeKind.CORRELATED_WITH and weight is None:
            raise IntegrityViolation(
                "a correlation edge must state its weight; an unweighted one "
                "asserts dependence without saying how much, and the discount "
                "could not be applied"
            )

        existing = session.execute(
            sa.select(KnowledgeEdge).where(
                KnowledgeEdge.source == source,
                KnowledgeEdge.target == target,
                KnowledgeEdge.kind == kind.value,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        edge = KnowledgeEdge(
            edge_id=uuid7(),
            source=source,
            target=target,
            kind=kind.value,
            weight=weight,
            evidence_ref=evidence_ref,
            note=note,
            created_by=created_by,
            created_at=at or self._clock.now(),
        )
        session.add(edge)
        session.flush()
        return edge

    # ----------------------------------------------------------------- read

    def node(self, session: Session, node_id: str) -> KnowledgeNode | None:
        return session.get(KnowledgeNode, node_id)

    def ancestors(self, session: Session, node_id: str, depth: int = 6) -> list[str]:
        """What this rests on, following DEPENDS_ON and SUPPORTS upward."""
        return self._walk(
            session,
            node_id,
            depth,
            kinds=(EdgeKind.DEPENDS_ON, EdgeKind.SUPPORTS),
            forward=True,
        )

    def descendants(self, session: Session, node_id: str, depth: int = 6) -> list[str]:
        """What breaks if this is wrong.

        The question a corpus most needs and least often can answer. When a
        deployed conclusion is questioned, this is the blast radius.
        """
        return self._walk(
            session,
            node_id,
            depth,
            kinds=(EdgeKind.DEPENDS_ON, EdgeKind.SUPPORTS),
            forward=False,
        )

    def _walk(
        self,
        session: Session,
        start: str,
        depth: int,
        *,
        kinds: tuple[EdgeKind, ...],
        forward: bool,
    ) -> list[str]:
        wanted = [k.value for k in kinds]
        seen: set[str] = {start}
        order: list[str] = []
        queue: deque[tuple[str, int]] = deque([(start, 0)])

        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            column = KnowledgeEdge.source if forward else KnowledgeEdge.target
            other = KnowledgeEdge.target if forward else KnowledgeEdge.source
            rows = session.execute(
                sa.select(other).where(column == current, KnowledgeEdge.kind.in_(wanted))
            ).scalars().all()
            for neighbour in sorted(rows):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                order.append(neighbour)
                queue.append((neighbour, level + 1))
        return order

    # ------------------------------------------------- independent support

    def independent_support(
        self,
        session: Session,
        node_id: str,
        *,
        threshold: Decimal = CORRELATION_THRESHOLD,
    ) -> IndependentSupport:
        """How many genuinely independent results support this claim.

        Supporting nodes joined by a correlation at or above ``threshold`` are
        collapsed into one, because they are one observation seen twice. The
        collapsing is transitive: if A correlates with B and B with C, all
        three are one piece of support, which is the conservative reading and
        the correct one when the alternative is over-counting.

        What was discounted is returned rather than absorbed. A number that
        quietly shrank would be indistinguishable from weak support, and those
        are very different situations.
        """
        supporting = tuple(
            sorted(
                session.execute(
                    sa.select(KnowledgeEdge.source).where(
                        KnowledgeEdge.target == node_id,
                        KnowledgeEdge.kind == EdgeKind.SUPPORTS.value,
                    )
                ).scalars()
            )
        )
        contradicting = tuple(
            sorted(
                session.execute(
                    sa.select(KnowledgeEdge.source).where(
                        KnowledgeEdge.target == node_id,
                        KnowledgeEdge.kind == EdgeKind.CONTRADICTS.value,
                    )
                ).scalars()
            )
        )

        if len(supporting) < 2:
            return IndependentSupport(
                node_id, supporting, len(supporting), (), contradicting
            )

        members = set(supporting)
        correlations = session.execute(
            sa.select(KnowledgeEdge).where(
                KnowledgeEdge.kind == EdgeKind.CORRELATED_WITH.value,
                KnowledgeEdge.source.in_(members),
                KnowledgeEdge.target.in_(members),
            )
        ).scalars().all()

        parent = {ref: ref for ref in supporting}

        def find(ref: str) -> str:
            while parent[ref] != ref:
                parent[ref] = parent[parent[ref]]
                ref = parent[ref]
            return ref

        discounted: list[tuple[str, str, Decimal]] = []
        for edge in sorted(correlations, key=lambda e: (e.source, e.target)):
            weight = edge.weight if edge.weight is not None else Decimal(0)
            if abs(weight) < threshold:
                continue
            left, right = find(edge.source), find(edge.target)
            discounted.append((edge.source, edge.target, weight))
            if left != right:
                parent[max(left, right)] = min(left, right)

        independent = len({find(ref) for ref in supporting})
        return IndependentSupport(
            node_id, supporting, independent, tuple(discounted), contradicting
        )

    # -------------------------------------------------------------- summary

    def counts(self, session: Session) -> dict[str, int]:
        nodes = session.execute(
            sa.select(KnowledgeNode.kind, sa.func.count()).group_by(KnowledgeNode.kind)
        ).all()
        edges = session.execute(
            sa.select(KnowledgeEdge.kind, sa.func.count()).group_by(KnowledgeEdge.kind)
        ).all()
        return {
            **{f"node:{kind}": int(n) for kind, n in nodes},
            **{f"edge:{kind}": int(n) for kind, n in edges},
        }
