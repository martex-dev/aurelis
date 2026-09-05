"""What the company knows, and where it came from.

Four kinds of record.

``knowledge_nodes`` / ``knowledge_edges`` are the graph. Its job is to answer
three questions and deliberately refuse more: what does this rest on, what
breaks if it is wrong, and **is the support actually independent**. It assigns
no confidence scores of its own — a graph that scored its nodes would invite
the reader to trust the score instead of the sources.

``lessons`` are what retrospectives concluded, some of which become standing
rules that apply to future work.

``corpus_trials`` is imported history from another system. Its figures are
stored **as published**, never recomputed: a deflated Sharpe of 0.99 computed
against sixty-five trials means something specific, and re-deflating it against
today's count would silently restate what someone actually reported.

``corpus_reconciliation`` records what an import's own totals claimed against
what its documents accounted for. The difference is carried, not distributed
by guess.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = [
    "CorpusReconciliation",
    "CorpusTrial",
    "KnowledgeEdge",
    "KnowledgeNode",
    "Lesson",
]


class KnowledgeNode(Base):
    """One thing the company knows about."""

    __tablename__ = "knowledge_nodes"

    node_id: Mapped[str] = mapped_column(sa.String(48), primary_key=True)
    """The subject's own reference — ``HYP-0001``, ``FND-0003``, ``TRIAL-H11``.
    Using the subject's reference as the key means an edge cannot point at a
    node that does not correspond to anything."""

    kind: Mapped[str] = mapped_column(sa.String(24), index=True)
    label: Mapped[str] = mapped_column(sa.Text)
    family: Mapped[str | None] = mapped_column(sa.String(96), index=True)
    desk: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    origin: Mapped[str] = mapped_column(sa.String(32), default="aurelis", index=True)
    """``aurelis`` or the name of the corpus it was imported from. A reader has
    to be able to tell what this company established from what it inherited."""

    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(index=True)


class KnowledgeEdge(Base):
    """One recorded relationship, with a citation.

    ``CORRELATED_WITH`` is the edge that does the real work: it carries the
    measured correlation between two pieces of support, and it is what stops
    repeated observations of one event from being counted as replication.
    """

    __tablename__ = "knowledge_edges"

    edge_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(sa.String(48), index=True)
    target: Mapped[str] = mapped_column(sa.String(48), index=True)
    kind: Mapped[str] = mapped_column(sa.String(24), index=True)

    weight: Mapped[Decimal | None] = mapped_column()
    """For ``CORRELATED_WITH``, the measured correlation. Required for that
    edge kind: an unweighted correlation edge would assert dependence without
    saying how much, and the discount could not be applied."""

    evidence_ref: Mapped[str | None] = mapped_column(sa.String(64))
    note: Mapped[str] = mapped_column(sa.Text, default="")
    created_by: Mapped[str] = mapped_column(sa.String(24))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.UniqueConstraint("source", "target", "kind", name="uq_edge_once"),
        sa.CheckConstraint("source <> target", name="ck_edge_not_self"),
        sa.CheckConstraint(
            "kind <> 'correlated_with' OR weight IS NOT NULL",
            name="ck_correlation_states_its_weight",
        ),
    )


class Lesson(Base):
    """Something the company learned, and may have made a rule about."""

    __tablename__ = "lessons"

    lesson_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    statement: Mapped[str] = mapped_column(sa.Text)
    source_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    """The retrospective, meeting or finding it came from. A lesson with no
    source is an opinion."""

    standing_rule: Mapped[bool] = mapped_column(default=False, index=True)
    """Whether this binds future work. Most lessons do not: a rule that
    accumulated automatically would eventually forbid everything."""

    applies_to: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    author: Mapped[str] = mapped_column(sa.String(24))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)
    retired_at: Mapped[dt.datetime | None] = mapped_column()
    retired_reason: Mapped[str] = mapped_column(sa.Text, default="")


class CorpusTrial(Base):
    """One trial imported from another research corpus, as published.

    Every figure here is stored exactly as the source reported it. ``dsr`` and
    ``dsr_n_trials`` travel together and are never recomputed — a deflated
    Sharpe means "this survived deflation against *that many* trials", and
    re-deflating it against a different count would quietly rewrite what
    somebody actually claimed.
    """

    __tablename__ = "corpus_trials"

    trial_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    corpus: Mapped[str] = mapped_column(sa.String(32), index=True)
    ref: Mapped[str] = mapped_column(sa.String(48), unique=True, index=True)

    hypothesis: Mapped[str] = mapped_column(sa.String(48), index=True)
    title: Mapped[str] = mapped_column(sa.String(256), default="")
    """What the entry is about, in words.

    The source names its entries ``H08``, which is unsearchable. The subject
    matter lives in the filename of the document each entry cites, so the title
    is read from there rather than invented -- it is the source's own words,
    reformatted, and never a summary written by this system."""

    family: Mapped[str] = mapped_column(sa.String(96), index=True)
    trial_count: Mapped[int] = mapped_column()
    """What this entry declared. Batched entries cover several trials."""

    ambiguous_allocation: Mapped[bool] = mapped_column(default=False)
    """The source said this entry's per-hypothesis split is not documented —
    only a program total. Carried rather than silently divided, because
    inventing the split would fabricate a research record."""

    grade: Mapped[str] = mapped_column(sa.String(24), index=True)
    protocol: Mapped[str] = mapped_column(sa.String(24), index=True)
    verdict: Mapped[str] = mapped_column(sa.String(24), index=True)
    maturity: Mapped[str] = mapped_column(sa.String(8))

    dsr: Mapped[Decimal | None] = mapped_column()
    """The figure, comparable. Stored through the money type, which fixes the
    scale at eight places — numerically identical to what was published, but no
    longer character-for-character what was written."""

    dsr_published: Mapped[str] = mapped_column(sa.String(32), default="")
    """The figure exactly as the source wrote it: ``0.99``, not ``0.99000000``.

    Kept alongside the comparable form because "reproduced as published" has to
    survive a database round-trip that pads the scale. Reports quote this;
    comparisons use ``dsr``."""

    dsr_n_trials: Mapped[int | None] = mapped_column()

    source: Mapped[str] = mapped_column(sa.Text)
    evidence: Mapped[str] = mapped_column(sa.Text)
    notes: Mapped[str] = mapped_column(sa.Text, default="")
    imported_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "(dsr IS NULL) = (dsr_n_trials IS NULL)",
            name="ck_dsr_travels_with_its_trial_count",
        ),
        sa.CheckConstraint("trial_count >= 1", name="ck_trial_count_positive"),
    )


class CorpusReconciliation(Base):
    """What an import claimed against what it could account for.

    The gap is a real property of the corpus, and it is carried rather than
    distributed by guess. An import that quietly made its numbers add up would
    be presenting a reconstruction as a verified figure.
    """

    __tablename__ = "corpus_reconciliations"

    corpus: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    source_version: Mapped[str] = mapped_column(sa.String(32))
    period: Mapped[str] = mapped_column(sa.String(16))

    claimed_total: Mapped[int] = mapped_column()
    claimed_run: Mapped[int] = mapped_column()
    claimed_data_blocked: Mapped[int] = mapped_column()
    documented_total: Mapped[int] = mapped_column()
    unallocated: Mapped[int] = mapped_column()
    unallocated_reason: Mapped[str] = mapped_column(sa.Text)

    entries: Mapped[int] = mapped_column()
    documents: Mapped[int] = mapped_column(default=0)
    digest: Mapped[str] = mapped_column(sa.String(64))
    """Hash of the source ledger. An import that ran twice against a changed
    corpus must be detectable."""

    imported_at: Mapped[dt.datetime] = mapped_column()

    @property
    def reconciles(self) -> bool:
        return self.documented_total + self.unallocated == self.claimed_total
