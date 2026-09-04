"""The ``aurelis`` command.

M0's surface is small on purpose: initialise a workspace, check it, verify the
record, and run the demonstration that proves the platform works. Commands for
the corporation itself arrive with the layers that own them.

Exit codes matter — this is called from CI and will be called from monitors:
``0`` healthy, ``1`` a problem the operator must repair, ``2`` misuse.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from aurelis import __version__
from aurelis.cli.demo import run_demo
from aurelis.cli.doctor import Status, run_checks
from aurelis.core.config import load_settings
from aurelis.runtime import Runtime

app = typer.Typer(
    name="aurelis",
    help="An autonomous quantitative research corporation.",
    no_args_is_help=True,
    add_completion=False,
)
db_app = typer.Typer(help="Workspace database.", no_args_is_help=True)
ledger_app = typer.Typer(help="The company's append-only record.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(ledger_app, name="ledger")

def _force_utf8() -> None:
    """Make the console safe for arbitrary text.

    Windows terminals still default to a legacy code page, and Rich renders
    box-drawing characters that cp1252 cannot encode -- which crashed
    ``aurelis doctor`` on CI before this existed. Agent output will be far
    less predictable than a box-drawing character, so the fix is at the
    stream rather than in the strings: encode as UTF-8, and replace anything
    the terminal genuinely cannot show rather than raising.

    A report that dies on an em dash is worse than a report with a question
    mark in it.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # An exotic stream that refuses to be reconfigured is not a reason
            # to fail: fall back to whatever it already does.
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


_force_utf8()
console = Console()

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_STATUS_STYLE = {
    Status.OK: ("[green]OK[/green]", "green"),
    Status.INFO: ("[cyan]INFO[/cyan]", "cyan"),
    Status.PROBLEM: ("[red]PROBLEM[/red]", "red"),
}


def _runtime(workspace: Path | None) -> Runtime:
    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"aurelis {__version__}")


@app.command()
def doctor(workspace: WorkspaceOption = None) -> None:
    """Check the installation, the workspace, the record and the model provider."""
    runtime = _runtime(workspace)
    try:
        checks = run_checks(runtime)
    finally:
        runtime.close()

    current_group = ""
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("", width=9)
    table.add_column("check", style="bold", width=28)
    table.add_column("detail", overflow="fold")

    for check in checks:
        if check.group != current_group:
            table.add_row("", f"[dim]── {check.group} ──[/dim]", "")
            current_group = check.group
        label, _ = _STATUS_STYLE[check.status]
        table.add_row(label, check.name, check.detail)

    console.print(table)

    problems = [c for c in checks if c.status is Status.PROBLEM]
    if problems:
        console.print(
            Panel(
                "\n".join(f"• {c.name}: {c.detail}" for c in problems),
                title=f"[red]{len(problems)} problem(s)[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)
    console.print("\n[green]Healthy.[/green]")


@db_app.command("init")
def db_init(workspace: WorkspaceOption = None) -> None:
    """Create the workspace, the schema and the invariant triggers.

    Idempotent: safe to run against a live workspace.
    """
    runtime = _runtime(workspace)
    try:
        triggers = runtime.initialise()
        console.print(f"workspace   {runtime.settings.workspace}")
        console.print(f"database    {runtime.settings.resolved_database_url}")
        console.print(f"objects     {runtime.settings.object_store}")
        console.print(
            f"invariants  {len(triggers)} append-only trigger(s) installed"
            if triggers
            else "invariants  [red]NOT installed — strict_integrity is off[/red]"
        )
        console.print("\n[green]Initialised.[/green] Next: [bold]aurelis doctor[/bold]")
    finally:
        runtime.close()


@ledger_app.command("verify")
def ledger_verify(workspace: WorkspaceOption = None) -> None:
    """Verify the hash chain end to end.

    Reads every event. Verification is an audit operation, and doing it
    incrementally would mean trusting a checkpoint written by the same code the
    audit is checking.
    """
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            result = runtime.ledger.verify(session)
    finally:
        runtime.close()

    if result.ok:
        console.print(f"[green]{result.describe()}[/green]")
        console.print("[dim]Tamper-evident, not tamper-proof: edits are detectable, "
                      "not impossible.[/dim]")
        return
    console.print(f"[red]{result.describe()}[/red]")
    raise typer.Exit(code=1)


@ledger_app.command("tail")
def ledger_tail(
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many events.")] = 20,
) -> None:
    """Show the most recent events — the beginning of the company timeline."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            events = runtime.ledger.tail(session, limit)
    finally:
        runtime.close()

    if not events:
        console.print("[dim]No events recorded yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("seq", justify="right", width=6)
    table.add_column("time", width=12)
    table.add_column("actor", width=14)
    table.add_column("kind", width=26)
    table.add_column("subject", width=16)
    for event in events:
        table.add_row(
            str(event.seq),
            event.created_at.strftime("%H:%M:%S.%f")[:12],
            event.actor,
            event.kind,
            event.subject or "[dim]—[/dim]",
        )
    console.print(table)


@app.command()
def demo(
    workspace: WorkspaceOption = None,
    rounds: Annotated[int, typer.Option(help="How many identical rounds to run.")] = 2,
) -> None:
    """Run M0's end-to-end proof: a scripted exchange, at zero cost.

    Two placeholder actors take turns through the whole platform — budget check
    at dispatch, task queued and claimed, model call recorded, output stored as
    a content-addressed artifact, every step chained. The second round is
    identical to the first and must be served entirely from cache.
    """
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        result = run_demo(runtime, rounds=rounds)
    finally:
        runtime.close()

    for actor, text in result.transcript:
        # Escaped: model output is arbitrary text and must never be parsed as
        # console markup. An agent that emits "[red]" should not colour the
        # terminal, and one that emits "[/]" should not corrupt it.
        console.print(
            Panel(escape(text), title=f"[bold]{escape(actor)}[/bold]", border_style="dim")
        )

    table = Table(show_header=False, box=None)
    table.add_column("", style="bold", width=16)
    table.add_column("")
    table.add_row("tasks", f"{result.tasks} succeeded")
    table.add_row("model calls", f"{result.model_calls} ({result.cache_hits} served from cache)")
    table.add_row("artifacts", str(result.artifacts))
    table.add_row("events", str(result.events))
    table.add_row("tokens", f"{result.tokens:,}")
    table.add_row(
        "cost",
        f"${result.usd:.6f}"
        + ("  [green](free — subscription or mock)[/green]" if result.free else ""),
    )
    table.add_row(
        "chain",
        f"[green]{result.chain_detail}[/green]"
        if result.chain_ok
        else f"[red]{result.chain_detail}[/red]",
    )
    console.print(table)

    if not result.chain_ok:
        raise typer.Exit(code=1)
    console.print("\n[green]M0 acceptance: platform verified end to end.[/green]")


if __name__ == "__main__":  # pragma: no cover
    app()
