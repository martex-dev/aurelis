"""Importing another organisation's research history.

martex-quant ran a hundred and twenty-five trials and wrote down what happened
to every one of them. Aurelis did not run those trials and cannot verify them,
but it can *know about them* — which is the difference between a company that
starts from zero and one that starts by reading the file.

Three rules govern this import, and they are the reason it is a module rather
than a script.

**Figures are preserved, never recomputed.** A deflated Sharpe of 0.99 means
"this survived deflation against sixty-five trials". Re-deflating it against
Aurelis's own trial count would produce a different number attributed to
someone who never computed it. So ``dsr`` and ``dsr_n_trials`` travel together
and are copied verbatim, and a database CHECK enforces that they arrive as a
pair.

**Everything is marked as inherited.** Every row carries ``origin`` naming the
corpus. A reader must always be able to tell what this company established from
what it read somewhere, and a knowledge base that blurs the two is worse than
one that stayed empty.

**The reconciliation gap is carried, not closed.** The source's own ledger
claims 125 trials; its committed documents account for 120. That five-trial gap
is a real property of the corpus — the source says so itself, in a comment
explaining that assigning it "would be fabrication". An importer that
distributed the difference across entries to make the arithmetic tidy would be
manufacturing exactly the kind of number this whole system exists to prevent.
So the gap is recorded as ``unallocated``, with the source's own reason, and
``reconciles`` is true precisely because ``documented + unallocated == claimed``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from importlib import util as import_util
from pathlib import Path, PurePosixPath
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import uuid7
from aurelis.memory.graph import KnowledgeGraph, NodeKind
from aurelis.memory.tables import CorpusReconciliation, CorpusTrial
from aurelis.platform.ledger.ledger import Ledger

__all__ = [
    "MARTEX_CORPUS",
    "CorpusNotAvailable",
    "ImportReport",
    "find_martex_bundle",
    "import_martex_corpus",
]

MARTEX_CORPUS = "martex-quant"

_LEDGER_PATH = ("docs", "research", "ledger", "trials.toml")
_HYPOTHESIS_DIR = ("docs", "hypotheses")


class CorpusNotAvailable(RuntimeError):
    """The corpus is not installed.

    Raised rather than returning an empty import. "We imported nothing" and
    "there was nothing to import" look identical in a database and justify
    completely different conclusions about how much the company knows.
    """


@dataclass(frozen=True, slots=True)
class ImportReport:
    """What arrived, and whether the source's own arithmetic held."""

    corpus: str
    trials: int
    documents: int
    claimed_total: int
    documented_total: int
    unallocated: int
    unallocated_reason: str
    digest: str
    nodes: int
    reimported: bool

    @property
    def reconciles(self) -> bool:
        """Whether the parts the import can see add up to what was claimed."""
        return self.documented_total + self.unallocated == self.claimed_total

    def describe(self) -> str:
        verb = "re-imported" if self.reimported else "imported"
        lines = [
            f"{verb} {self.trials} ledger entries from {self.corpus} "
            f"({self.documents} hypothesis documents, digest {self.digest[:12]})",
            f"  claimed by the source      {self.claimed_total}",
            f"  documented by its entries  {self.documented_total}",
            f"  unallocated                {self.unallocated}",
        ]
        if self.unallocated:
            lines.append(f"  carried because            {self.unallocated_reason}")
        lines.append(
            "  reconciles                 "
            + ("yes" if self.reconciles else "NO — the import is not trustworthy")
        )
        return "\n".join(lines)


def find_martex_bundle() -> Path:
    """Locate the research bundle inside the installed martex-quant package.

    The corpus ships *inside the wheel* rather than being fetched, so an import
    either finds the exact files the installed version carries or fails. A
    downloader would make "which corpus did we import?" depend on when the
    import ran.
    """
    spec = import_util.find_spec("martex_quant")
    if spec is None or not spec.origin:
        raise CorpusNotAvailable(
            "martex-quant is not installed, so its research history cannot be "
            "imported. Aurelis runs without it; it simply starts without that "
            "corpus, and the prior-art search will say so."
        )
    bundle = Path(spec.origin).parent / "_bundle"
    if not (bundle.joinpath(*_LEDGER_PATH)).exists():
        raise CorpusNotAvailable(
            f"martex-quant is installed at {bundle.parent} but carries no "
            f"research bundle at {bundle}; nothing to import."
        )
    return bundle


def import_martex_corpus(
    session: Session,
    *,
    bundle: Path | None = None,
    ledger: Ledger | None = None,
    clock: Clock | None = None,
    graph: KnowledgeGraph | None = None,
    at: dt.datetime | None = None,
) -> ImportReport:
    """Read the corpus into institutional memory. Idempotent.

    Running it twice against the same bundle changes nothing and reports
    ``reimported``. Running it against a *changed* bundle is detectable,
    because the reconciliation row stores the digest of the source file.
    """
    the_clock = clock or SystemClock()
    moment = at or the_clock.now()
    the_graph = graph or KnowledgeGraph(the_clock)
    root = bundle or find_martex_bundle()

    ledger_file = root.joinpath(*_LEDGER_PATH)
    if not ledger_file.exists():
        raise CorpusNotAvailable(
            f"no trial ledger at {ledger_file}; there is nothing to import, "
            "which is not the same as importing nothing"
        )
    raw = ledger_file.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    document = tomllib.loads(raw.decode("utf-8"))

    entries: list[dict[str, Any]] = list(document.get("entries", ()))
    if not entries:
        raise CorpusNotAvailable(f"{ledger_file} declares no entries")

    documents = sorted(root.joinpath(*_HYPOTHESIS_DIR).glob("*.md"))
    claimed_total = int(document["ledger_total_claimed"])
    documented_total = sum(int(entry["trial_count"]) for entry in entries)
    unallocated = claimed_total - documented_total
    reason = str(document.get("unallocated", {}).get("reason", "")) or (
        "the source states no reason; the gap is carried unexplained"
    )
    if unallocated == 0:
        reason = "the source's entries account for its claimed total exactly"

    existing = session.get(CorpusReconciliation, MARTEX_CORPUS)
    reimported = existing is not None

    written = 0
    nodes = 0
    for entry in entries:
        ref = f"MQ-{entry['hypothesis']}"
        row = session.execute(
            sa.select(CorpusTrial).where(CorpusTrial.ref == ref)
        ).scalar_one_or_none()
        values = _trial_values(entry, moment)
        if row is None:
            session.add(CorpusTrial(trial_id=uuid7(), ref=ref, **values))
            written += 1
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.flush()

        before = the_graph.node(session, ref)
        the_graph.add_node(
            session,
            node_id=ref,
            kind=NodeKind.TRIAL,
            label=f"{_title(entry)} — {_label(entry)}",
            family=str(entry["family"]),
            origin=MARTEX_CORPUS,
            payload={
                "verdict": str(entry["verdict"]),
                "trial_count": int(entry["trial_count"]),
                "run_count": entry.get("run_count"),
                "selection_set": entry.get("selection_set"),
                "source": str(entry.get("source", "")),
                "maturity": str(entry.get("maturity", "")),
            },
            at=moment,
        )
        if before is None:
            nodes += 1

    reconciliation = existing or CorpusReconciliation(corpus=MARTEX_CORPUS)
    reconciliation.source_version = str(document.get("period", "unknown"))
    reconciliation.period = str(document.get("period", "unknown"))
    reconciliation.claimed_total = claimed_total
    reconciliation.claimed_run = int(document.get("ledger_run_claimed", claimed_total))
    reconciliation.claimed_data_blocked = int(
        document.get("ledger_data_blocked_claimed", 0)
    )
    reconciliation.documented_total = documented_total
    reconciliation.unallocated = unallocated
    reconciliation.unallocated_reason = reason
    reconciliation.entries = len(entries)
    reconciliation.documents = len(documents)
    reconciliation.digest = digest
    reconciliation.imported_at = moment
    session.add(reconciliation)
    session.flush()

    report = ImportReport(
        corpus=MARTEX_CORPUS,
        trials=len(entries),
        documents=len(documents),
        claimed_total=claimed_total,
        documented_total=documented_total,
        unallocated=unallocated,
        unallocated_reason=reason,
        digest=digest,
        nodes=nodes,
        reimported=reimported,
    )

    if ledger is not None:
        ledger.append(
            session,
            kind=EventKind.CORPUS_IMPORTED,
            actor=Actor.OPERATOR,
            subject=MARTEX_CORPUS,
            payload={
                "entries": len(entries),
                "new_rows": written,
                "new_nodes": nodes,
                "documents": len(documents),
                "digest": digest,
                "reimported": reimported,
            },
            at=moment,
        )
        ledger.append(
            session,
            kind=EventKind.CORPUS_RECONCILED,
            actor=Actor.SYSTEM,
            subject=MARTEX_CORPUS,
            payload={
                "claimed_total": claimed_total,
                "documented_total": documented_total,
                "unallocated": unallocated,
                "reason": reason,
                "reconciles": report.reconciles,
            },
            at=moment,
        )
    return report


def _trial_values(entry: dict[str, Any], moment: dt.datetime) -> dict[str, Any]:
    """Copy one ledger entry, converting nothing that carries meaning.

    ``dsr`` becomes a ``Decimal`` from its *string* form, never from the float
    tomllib produced, so 0.777 stays 0.777 rather than becoming a binary
    approximation with a tail of digits nobody published.
    """
    dsr = entry.get("dsr")
    dsr_n = entry.get("dsr_n_trials")
    if (dsr is None) != (dsr_n is None):
        raise ValueError(
            f"{entry['hypothesis']} publishes a deflated Sharpe without the "
            "trial count it was deflated against; the figure would be "
            "meaningless on its own"
        )
    return {
        "corpus": MARTEX_CORPUS,
        "hypothesis": str(entry["hypothesis"]),
        "title": _title(entry),
        "family": str(entry["family"]),
        "trial_count": int(entry["trial_count"]),
        "ambiguous_allocation": bool(entry.get("ambiguous_allocation", False)),
        "grade": str(entry.get("grade", "")),
        "protocol": str(entry.get("protocol", "")),
        "verdict": str(entry["verdict"]),
        "maturity": str(entry.get("maturity", "")),
        "dsr": None if dsr is None else Decimal(repr(dsr)),
        "dsr_published": "" if dsr is None else repr(dsr),
        "dsr_n_trials": None if dsr_n is None else int(dsr_n),
        "source": str(entry.get("source", "")),
        "evidence": str(entry.get("evidence", "")),
        "notes": str(entry.get("notes", "")),
        "imported_at": moment,
    }


def _title(entry: dict[str, Any]) -> str:
    """The subject of an entry, read out of the document it cites.

    ``docs/hypotheses/08-funding-extremes.md`` becomes "funding extremes". The
    corpus names its entries ``H08``, which tells a prior-art search nothing;
    the filename is the closest thing to a title the source actually wrote, so
    it is reformatted rather than summarised. Numeric leading segments are the
    hypothesis numbers and carry no subject matter.

    An entry citing something without a usable name keeps its identifier, which
    searches badly — correctly. Inventing a description would put this system's
    words into another organisation's record.
    """
    stem = PurePosixPath(str(entry.get("source", ""))).stem
    words = [
        word
        for word in stem.replace("_", "-").split("-")
        if word and not word.isdigit()
    ]
    return " ".join(words) or str(entry["hypothesis"])


def _label(entry: dict[str, Any]) -> str:
    return (
        f"{entry['hypothesis']} ({entry['family']}): {entry['verdict']}, "
        f"{entry['trial_count']} trials — {entry.get('evidence', '')}"
    )


# The importer draws NO edges.
#
# It is tempting: the corpus has a "superseded" verdict, families that share a
# prefix, and prose in `notes` describing which finding replaced which. Every
# one of those is an inference somebody would have to defend, and a link
# Aurelis invented between two of another organisation's trials would be this
# company's opinion wearing somebody else's citation.
#
# What the source *does* state explicitly is carried on each node's payload —
# `selection_set` in particular, which says two entries came out of the same
# search and so are not independent evidence of each other. An Aurelis
# researcher who reads that and records a CORRELATED_WITH edge has made a
# judgement, signed it, and can be argued with. The importer cannot.
