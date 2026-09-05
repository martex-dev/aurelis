"""``aurelis memory`` — the corpus, and what it will not let you forget.

Five commands, each one an answer to a question a research organisation should
be able to answer instantly and usually cannot: what have we inherited, has
anyone tried this, how much of this support is really independent, what are we
entitled to believe, and what binds the next piece of work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.memory.confidence import assess
from aurelis.memory.corpus import CorpusNotAvailable, import_martex_corpus
from aurelis.memory.graph import KnowledgeGraph
from aurelis.memory.lessons import Lessons
from aurelis.memory.mirror import mirror_research
from aurelis.memory.priorart import search
from aurelis.memory.tables import CorpusReconciliation, CorpusTrial
from aurelis.memory.vault import export_vault
from aurelis.research.tables import Finding
from aurelis.runtime import Runtime

console = Console()

memory_app = typer.Typer(
    help="Institutional memory: prior art, the knowledge graph, and the vault.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@memory_app.command("import")
def memory_import(
    workspace: WorkspaceOption = None,
    bundle: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Research bundle to read. Defaults to the snapshot inside the "
                "installed martex-quant wheel; point it at a live repository "
                "to import that corpus instead."
            )
        ),
    ] = None,
) -> None:
    """Import the martex-quant research corpus, preserving its own figures.

    Idempotent. Nothing is recomputed and the reconciliation gap is carried
    rather than closed, so the import either reproduces the source's claimed
    totals or says plainly that it does not.

    The default source is the snapshot bundled in the installed wheel, so an
    import is reproducible from the lockfile alone. ``--bundle`` reads a live
    repository instead; the reconciliation row stores the source digest either
    way, so which corpus is loaded is always answerable.
    """
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            try:
                report = import_martex_corpus(
                    session,
                    bundle=bundle,
                    ledger=runtime.ledger,
                    clock=runtime.clock,
                    graph=runtime.graph,
                )
            except CorpusNotAvailable as error:
                console.print(f"[yellow]{escape(str(error))}[/yellow]")
                raise typer.Exit(0) from None
        console.print(escape(report.describe()))
        if not report.reconciles:
            raise typer.Exit(1)
    finally:
        runtime.close()


@memory_app.command("sync")
def memory_sync(workspace: WorkspaceOption = None) -> None:
    """Project the research record onto the knowledge graph.

    A projection, not a second copy: it draws only relationships the record
    already states, and running it twice changes nothing.
    """
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            report = mirror_research(
                session, graph=runtime.graph, ledger=runtime.ledger, clock=runtime.clock
            )
        console.print(escape(report.describe()))
    finally:
        runtime.close()


@memory_app.command("prior-art")
def memory_prior_art(
    claim: Annotated[str, typer.Argument(help="The claim to check for prior art.")],
    family: Annotated[
        str, typer.Option(help="Hierarchical family, e.g. info.derivatives.funding.")
    ] = "",
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option(help="How many matches to show.")] = 8,
) -> None:
    """Ask whether anyone has tried this before."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            report = search(session, claim=claim, family=family, limit=limit)
        console.print(escape(report.describe()))
        if report.searched and report.novel:
            console.print(
                "[dim]No close match. That is a statement about this index, "
                "not about the world.[/dim]"
            )
    finally:
        runtime.close()


@memory_app.command("support")
def memory_support(
    node: Annotated[str, typer.Argument(help="Node reference, e.g. HYP-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """How much of a claim's support is genuinely independent."""
    runtime = _runtime(workspace)
    try:
        graph = KnowledgeGraph(runtime.clock)
        with runtime.database.session() as session:
            support = graph.independent_support(session, node)
            ancestors = graph.ancestors(session, node)
            descendants = graph.descendants(session, node)
        console.print(escape(support.describe()))
        if support.overcounted_by:
            console.print(
                f"[yellow]counting supporters naively would have said "
                f"{support.naive}, overstating it by "
                f"{support.overcounted_by}[/yellow]"
            )
        if ancestors:
            console.print(f"  rests on      {escape(', '.join(ancestors))}")
        if descendants:
            console.print(
                f"  breaks with it {escape(', '.join(descendants))}"
            )
    finally:
        runtime.close()


@memory_app.command("confidence")
def memory_confidence(
    finding_ref: Annotated[str, typer.Argument(help="Finding reference, e.g. FND-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """What the record entitles the company to believe, and why not more."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            finding = session.execute(
                sa.select(Finding).where(Finding.ref == finding_ref)
            ).scalar_one_or_none()
            if finding is None:
                console.print(f"[red]no finding {finding_ref}[/red]")
                raise typer.Exit(2)
            confidence = assess(session, finding, graph=runtime.graph)

        console.print(f"{finding_ref}  [bold]{confidence.band.label}[/bold]")
        console.print(f"  verdict            {escape(finding.verdict)}")
        console.print(f"  independent support {confidence.support.independent}")
        console.print(f"  replications        {confidence.replications}")
        console.print(f"  open objections     {confidence.open_objections}")
        for reason in confidence.caps:
            console.print(f"  capped by          {escape(reason)}")
    finally:
        runtime.close()


@memory_app.command("rules")
def memory_rules(
    family: Annotated[str, typer.Option(help="Family the work sits in.")] = "",
    desk: Annotated[str | None, typer.Option(help="Desk the work sits on.")] = None,
    workspace: WorkspaceOption = None,
) -> None:
    """The standing rules that bind a piece of work."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rules = Lessons(runtime.ledger, runtime.clock).binding(
                session, family=family, desk=desk
            )
        console.print(escape(rules.describe()))
    finally:
        runtime.close()


@memory_app.command("corpus")
def memory_corpus(workspace: WorkspaceOption = None) -> None:
    """What has been inherited, and whether its own totals add up."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            reconciliations = list(
                session.execute(sa.select(CorpusReconciliation)).scalars()
            )
            trials = list(
                session.execute(
                    sa.select(CorpusTrial).order_by(CorpusTrial.ref)
                ).scalars()
            )

        if not reconciliations:
            console.print("[yellow]no corpus imported[/yellow]")
            raise typer.Exit(0)

        for row in reconciliations:
            console.print(f"[bold]{escape(row.corpus)}[/bold] ({row.period})")
            console.print(f"  claimed by the source     {row.claimed_total}")
            console.print(f"  documented by its entries {row.documented_total}")
            console.print(f"  unallocated               {row.unallocated}")
            console.print(
                "  reconciles                "
                + ("[green]yes[/green]" if row.reconciles else "[red]NO[/red]")
            )
            if row.unallocated:
                console.print(f"  carried because           {escape(row.unallocated_reason)}")

        table = Table(title="inherited trials", show_lines=False)
        for column in ("ref", "family", "verdict", "trials", "DSR as published"):
            table.add_column(column)
        for trial in trials:
            published = (
                f"{trial.dsr_published} against {trial.dsr_n_trials}"
                if trial.dsr is not None
                else ""
            )
            table.add_row(
                trial.ref,
                trial.family,
                trial.verdict,
                str(trial.trial_count) + ("*" if trial.ambiguous_allocation else ""),
                published,
            )
        console.print(table)
        console.print("[dim]* per-hypothesis split not documented by the source[/dim]")
    finally:
        runtime.close()


@memory_app.command("export")
def memory_export(
    workspace: WorkspaceOption = None,
    out: Annotated[
        Path | None, typer.Option(help="Where to write the vault. Defaults to <workspace>/vault.")
    ] = None,
) -> None:
    """Render the corpus as an Obsidian-compatible vault.

    One way only. The directory is rewritten on every export and nothing reads
    it back, so it is safe to browse and pointless to edit.
    """
    runtime = _runtime(workspace)
    try:
        root = out or (runtime.settings.workspace / "vault")
        with runtime.database.session() as session:
            report = export_vault(
                session, root, ledger=runtime.ledger, clock=runtime.clock, graph=runtime.graph
            )
        console.print(escape(report.describe()))
    finally:
        runtime.close()
