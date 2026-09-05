"""The Obsidian vault: a rendering, not a database.

Markdown in a linked vault is the best interface a human has for reading a
research corpus — backlinks, graph view, full-text search, and no application
to launch. It is also a terrible place to *keep* the corpus, because a
directory of files anyone can edit has no invariants, no transactions and no
way to tell an authoritative statement from a note somebody typed in a hurry.

So the vault is generated **one way, always**. The database is the record; the
vault is a view of it, rewritten from scratch on every export. Nothing reads a
vault file back, and this module offers no function that could — which is what
makes it safe for a human to scribble in the margin, and why every generated
page says so at the top.

That constraint has a price worth naming: notes a person adds inside the export
directory are lost on the next export. The alternative — merging human edits
back into the record — would mean the company's evidence base could be changed
by editing a text file, with no author, no timestamp and no review. The
directory is disposable so that the corpus does not have to be.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.memory.confidence import assess
from aurelis.memory.graph import KnowledgeGraph
from aurelis.memory.tables import CorpusReconciliation, CorpusTrial, Lesson
from aurelis.platform.ledger.ledger import Ledger
from aurelis.research.tables import Finding, Hypothesis

__all__ = ["ExportReport", "export_vault"]

_BANNER = (
    "> [!warning] Generated file\n"
    "> This page is rendered from the Aurelis database and is rewritten on "
    "every export.\n> Edits made here are not read back and will be lost. "
    "The database is the record.\n"
)


@dataclass(frozen=True, slots=True)
class ExportReport:
    """What was written where."""

    root: Path
    hypotheses: int
    findings: int
    trials: int
    lessons: int

    @property
    def pages(self) -> int:
        return self.hypotheses + self.findings + self.trials + self.lessons + 1

    def describe(self) -> str:
        return (
            f"exported {self.pages} pages to {self.root}\n"
            f"  hypotheses {self.hypotheses}\n"
            f"  findings   {self.findings}\n"
            f"  trials     {self.trials}\n"
            f"  lessons    {self.lessons}"
        )


def export_vault(
    session: Session,
    root: Path,
    *,
    ledger: Ledger | None = None,
    clock: Clock | None = None,
    graph: KnowledgeGraph | None = None,
    at: dt.datetime | None = None,
) -> ExportReport:
    """Render the corpus as a linked Markdown vault.

    Writes into ``root`` and creates it if needed. Existing generated pages are
    overwritten; nothing is read first, because reading would imply the file
    could say something the database does not.
    """
    the_clock = clock or SystemClock()
    moment = at or the_clock.now()
    the_graph = graph or KnowledgeGraph(the_clock)

    for folder in ("hypotheses", "findings", "trials", "lessons"):
        (root / folder).mkdir(parents=True, exist_ok=True)

    hypotheses = list(
        session.execute(sa.select(Hypothesis).order_by(Hypothesis.ref)).scalars()
    )
    findings = list(session.execute(sa.select(Finding).order_by(Finding.ref)).scalars())
    trials = list(session.execute(sa.select(CorpusTrial).order_by(CorpusTrial.ref)).scalars())
    lessons = list(session.execute(sa.select(Lesson).order_by(Lesson.ref)).scalars())

    findings_by_hypothesis: dict[str, list[Finding]] = {}
    for finding in findings:
        findings_by_hypothesis.setdefault(finding.hypothesis_ref, []).append(finding)

    for hypothesis in hypotheses:
        _write(
            root / "hypotheses" / f"{hypothesis.ref}.md",
            _hypothesis_page(
                hypothesis, findings_by_hypothesis.get(hypothesis.ref, []), the_graph, session
            ),
        )
    for finding in findings:
        _write(
            root / "findings" / f"{finding.ref}.md",
            _finding_page(session, finding, the_graph),
        )
    for trial in trials:
        _write(root / "trials" / f"{trial.ref}.md", _trial_page(trial))
    for lesson in lessons:
        _write(root / "lessons" / f"{lesson.ref}.md", _lesson_page(lesson))

    _write(
        root / "Corpus.md",
        _index_page(session, hypotheses, findings, trials, lessons, moment),
    )

    report = ExportReport(
        root=root,
        hypotheses=len(hypotheses),
        findings=len(findings),
        trials=len(trials),
        lessons=len(lessons),
    )
    if ledger is not None:
        ledger.append(
            session,
            kind=EventKind.VAULT_EXPORTED,
            actor=Actor.OPERATOR,
            subject=str(root),
            payload={
                "pages": report.pages,
                "hypotheses": report.hypotheses,
                "findings": report.findings,
                "trials": report.trials,
                "lessons": report.lessons,
            },
            at=moment,
        )
    return report


def _write(path: Path, body: str) -> None:
    path.write_text(_BANNER + "\n" + body, encoding="utf-8")


def _frontmatter(**fields: object) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            if not value:
                continue
            lines.append(f"{key}: [{', '.join(str(item) for item in value)}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _hypothesis_page(
    hypothesis: Hypothesis,
    findings: list[Finding],
    graph: KnowledgeGraph,
    session: Session,
) -> str:
    support = graph.independent_support(session, hypothesis.ref)
    parts = [
        _frontmatter(
            ref=hypothesis.ref,
            kind="hypothesis",
            state=hypothesis.state,
            family=hypothesis.family,
            desk=hypothesis.desk,
            author=hypothesis.author,
            origin="aurelis",
        ),
        f"\n# {hypothesis.ref}\n",
        f"\n{hypothesis.claim}\n",
        "\n## State\n",
        f"\n`{hypothesis.state}`",
    ]
    if hypothesis.verdict_reason:
        parts.append(f" — {hypothesis.verdict_reason}")
    parts.append("\n\n## Support\n\n" + support.describe() + "\n")

    if hypothesis.rationale:
        parts.append(f"\n## Rationale\n\n{hypothesis.rationale}\n")
    parts.append(
        f"\n## Declared before the run\n\n"
        f"- primary metric: `{hypothesis.primary_metric}`\n"
        f"- minimum effect worth caring about: `{hypothesis.minimum_effect}`\n"
    )
    if hypothesis.prior_art:
        links = ", ".join(f"[[{str(ref)}]]" for ref in hypothesis.prior_art)
        parts.append(f"\n## Prior art\n\n{links}\n")
    if hypothesis.parent_ref:
        parts.append(
            f"\n## Derivation\n\n{hypothesis.derivation} of "
            f"[[{hypothesis.parent_ref}]]\n"
        )
    if findings:
        rendered = "\n".join(
            f"- [[{finding.ref}]] — {finding.verdict}" for finding in findings
        )
        parts.append(f"\n## Findings\n\n{rendered}\n")
    return "".join(parts)


def _finding_page(session: Session, finding: Finding, graph: KnowledgeGraph) -> str:
    confidence = assess(session, finding, graph=graph)
    parts = [
        _frontmatter(
            ref=finding.ref,
            kind="finding",
            verdict=finding.verdict,
            confidence=confidence.band.label,
            author=finding.author,
            origin="aurelis",
        ),
        f"\n# {finding.ref}\n",
        f"\n{finding.statement}\n",
        f"\n## Verdict\n\n`{finding.verdict}` — {finding.verdict_reason}\n",
        f"\n## Confidence\n\n**{confidence.band.label}**\n",
    ]
    if confidence.caps:
        parts.append(
            "\nCapped by:\n\n"
            + "\n".join(f"- {reason}" for reason in confidence.caps)
            + "\n"
        )
    else:
        parts.append("\nNothing on the record caps it.\n")
    parts.append(
        f"\nDerived from the record at export time, not stored. "
        f"{confidence.support.describe()}\n"
    )
    parts.append(f"\n## Hypothesis\n\n[[{finding.hypothesis_ref}]]\n")
    if finding.run_ref:
        parts.append(f"\n## Run\n\n`{finding.run_ref}`\n")
    return "".join(parts)


def _trial_page(trial: CorpusTrial) -> str:
    parts = [
        _frontmatter(
            ref=trial.ref,
            kind="trial",
            origin=trial.corpus,
            verdict=trial.verdict,
            family=trial.family,
            grade=trial.grade,
            protocol=trial.protocol,
            maturity=trial.maturity,
            title=trial.title,
        ),
        f"\n# {trial.ref} — {trial.title}\n" if trial.title else f"\n# {trial.ref}\n",
        f"\n> Inherited from **{trial.corpus}**. Aurelis did not run this and "
        "cannot verify it; the figures below are reproduced as published.\n",
        f"\n- hypothesis: `{trial.hypothesis}`\n"
        f"- family: `{trial.family}`\n"
        f"- verdict: `{trial.verdict}`\n"
        f"- trials declared: {trial.trial_count}\n",
    ]
    if trial.ambiguous_allocation:
        parts.append(
            "- **allocation ambiguous**: the source documents only a program "
            "total, not a per-hypothesis split\n"
        )
    if trial.dsr is not None:
        parts.append(
            f"- deflated Sharpe as published: **{trial.dsr_published}**, deflated against "
            f"{trial.dsr_n_trials} trials (not recomputed)\n"
        )
    parts.append(f"\n## Evidence cited by the source\n\n{trial.evidence}\n")
    if trial.notes:
        parts.append(f"\n## Notes\n\n{trial.notes}\n")
    parts.append(f"\n## Source document\n\n`{trial.source}`\n")
    return "".join(parts)


def _lesson_page(lesson: Lesson) -> str:
    status = "retired" if lesson.retired_at else (
        "standing rule" if lesson.standing_rule else "lesson"
    )
    parts = [
        _frontmatter(
            ref=lesson.ref,
            kind="lesson",
            status=status,
            author=lesson.author,
            applies_to=[str(item) for item in lesson.applies_to],
        ),
        f"\n# {lesson.ref}\n",
        f"\n{lesson.statement}\n",
        f"\n## Status\n\n`{status}`\n",
    ]
    if lesson.source_ref:
        parts.append(f"\n## Learned from\n\n[[{lesson.source_ref}]]\n")
    if lesson.retired_at:
        parts.append(f"\n## Retired\n\n{lesson.retired_reason}\n")
    return "".join(parts)


def _index_page(
    session: Session,
    hypotheses: list[Hypothesis],
    findings: list[Finding],
    trials: list[CorpusTrial],
    lessons: list[Lesson],
    moment: dt.datetime,
) -> str:
    parts = [
        _frontmatter(kind="index", exported_at=moment.isoformat()),
        "\n# Corpus\n",
        f"\nExported {moment.isoformat()}.\n",
        f"\n- {len(hypotheses)} hypotheses\n"
        f"- {len(findings)} findings\n"
        f"- {len(trials)} inherited trials\n"
        f"- {len(lessons)} lessons\n",
    ]

    graveyard = [h for h in hypotheses if h.state in ("refuted", "shelved")]
    if graveyard:
        parts.append(
            "\n## Killed\n\nWhat the company tried and dropped. Listed first "
            "on purpose: a corpus that only shows what survived has forgotten "
            "what it cost to get there.\n\n"
            + "\n".join(f"- [[{h.ref}]] — {h.state}" for h in graveyard)
            + "\n"
        )

    for reconciliation in session.execute(
        sa.select(CorpusReconciliation).order_by(CorpusReconciliation.corpus)
    ).scalars():
        parts.append(
            f"\n## Inherited from {reconciliation.corpus}\n\n"
            f"- claimed by the source: **{reconciliation.claimed_total}** trials "
            f"({reconciliation.claimed_run} run, "
            f"{reconciliation.claimed_data_blocked} data-blocked)\n"
            f"- documented by its own entries: **{reconciliation.documented_total}**\n"
            f"- unallocated: **{reconciliation.unallocated}**\n"
            f"- reconciles: {'yes' if reconciliation.reconciles else 'NO'}\n"
        )
        if reconciliation.unallocated:
            parts.append(
                f"\nThe gap is carried, not distributed. The source's own "
                f"reason: {reconciliation.unallocated_reason}\n"
            )

    if hypotheses:
        parts.append(
            "\n## All hypotheses\n\n"
            + "\n".join(f"- [[{h.ref}]] — {h.state}" for h in hypotheses)
            + "\n"
        )
    if trials:
        parts.append(
            "\n## All inherited trials\n\n"
            + "\n".join(f"- [[{t.ref}]] — {t.verdict}" for t in trials)
            + "\n"
        )
    return "".join(parts)
