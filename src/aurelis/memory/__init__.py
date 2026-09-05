"""Institutional memory: what the company knows, and where it came from.

Four things live here, and the boundaries between them are the design.

The **graph** records relationships and refuses to score them. Its one piece of
arithmetic is independent support, which collapses evidence joined by a
correlation above the threshold and reports what it discounted rather than
silently returning a smaller number.

**Confidence** is derived on read, never stored — which is what makes "a
finding's confidence degrades when an objection opens against it" true without
anybody having to remember to update a column.

**Prior art** answers "have we tried this before?" deterministically, over the
company's own hypotheses and every imported corpus at once, and distinguishes
*searched and found nothing* from *nothing to search*.

**Lessons** separate what somebody concluded from the few conclusions that bind
future work, because a rulebook that accumulates automatically eventually
forbids everything.

The **vault** renders all of it as linked Markdown, one way only. The database
is the record; the vault is a view, and nothing reads it back.
"""

from aurelis.memory.brainstorm import (
    BrainstormOutcome,
    evidence_pack,
    hold_brainstorm,
)
from aurelis.memory.confidence import Confidence, ConfidenceBand, assess, write_cap_reason
from aurelis.memory.corpus import (
    MARTEX_CORPUS,
    CorpusNotAvailable,
    ImportReport,
    find_martex_bundle,
    import_martex_corpus,
)
from aurelis.memory.graph import (
    CORRELATION_THRESHOLD,
    EdgeKind,
    IndependentSupport,
    KnowledgeGraph,
    NodeKind,
)
from aurelis.memory.lessons import Lessons, StandingRules
from aurelis.memory.mirror import MirrorReport, mirror_research
from aurelis.memory.priorart import PriorArt, PriorArtReport, search
from aurelis.memory.tables import (
    CorpusReconciliation,
    CorpusTrial,
    KnowledgeEdge,
    KnowledgeNode,
    Lesson,
)
from aurelis.memory.vault import ExportReport, export_vault

__all__ = [
    "CORRELATION_THRESHOLD",
    "BrainstormOutcome",
    "MARTEX_CORPUS",
    "Confidence",
    "ConfidenceBand",
    "CorpusNotAvailable",
    "CorpusReconciliation",
    "CorpusTrial",
    "EdgeKind",
    "ExportReport",
    "ImportReport",
    "IndependentSupport",
    "KnowledgeEdge",
    "KnowledgeGraph",
    "KnowledgeNode",
    "Lesson",
    "Lessons",
    "MirrorReport",
    "NodeKind",
    "PriorArt",
    "PriorArtReport",
    "StandingRules",
    "assess",
    "evidence_pack",
    "export_vault",
    "find_martex_bundle",
    "hold_brainstorm",
    "import_martex_corpus",
    "mirror_research",
    "search",
    "write_cap_reason",
]
