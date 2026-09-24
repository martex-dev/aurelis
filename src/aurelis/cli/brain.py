"""``aurelis brain`` — the shared brain every agent reads, and the vault."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

brain_app = typer.Typer(
    help="The shared brain: what every agent reads, the notes they leave, and the vault.",
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


@brain_app.command("show")
def brain_show(
    workspace: WorkspaceOption = None,
    topic: Annotated[
        list[str] | None,
        typer.Option(help="An instrument, event kind or mechanism the seat is looking at."),
    ] = None,
) -> None:
    """Print the brain exactly as an agent at a seat reads it."""
    from aurelis.brain.briefing import briefing

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            text = briefing(session, topics=tuple(topic or ())).text()
    finally:
        runtime.close()
    console.print(escape(text))


@brain_app.command("notes")
def brain_notes(
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option(help="How many, newest first.")] = 30,
) -> None:
    """The notes agents and the operator left in the brain."""
    from aurelis.brain.notes import recent_notes

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            rows = [
                (n.ref, n.written_at, n.author, ", ".join(n.topics or []), n.text)
                for n in recent_notes(session, limit=limit)
            ]
    finally:
        runtime.close()
    table = Table(title="shared brain notes")
    for column in ("ref", "at", "author", "about", "note"):
        table.add_column(column, overflow="fold")
    for ref, at, author, about, text in rows:
        table.add_row(ref, at.strftime("%m-%d %H:%M"), author, escape(about), escape(text))
    console.print(table)


@brain_app.command("note")
def brain_note(
    text: Annotated[str, typer.Argument(help="The note, in a sentence or two.")],
    workspace: WorkspaceOption = None,
    topic: Annotated[
        list[str] | None, typer.Option(help="What it is about: BTC-USD, MEC-0001, memecoin.")
    ] = None,
) -> None:
    """Add a note to the brain as the operator. Every agent reads it from now on."""
    from aurelis.brain.notes import OPERATOR, write_note

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            row = write_note(
                session,
                author=OPERATOR,
                text=text,
                topics=tuple(topic or ()),
                source_ref="cli",
                ledger=runtime.ledger,
                at=runtime.clock.now(),
            )
            ref = row.ref if row is not None else None
    finally:
        runtime.close()
    if ref is None:
        console.print(
            "[yellow]Not recorded: too short, or the same note was already there.[/yellow]"
        )
        raise typer.Exit(code=1)
    console.print(
        f"[green]{ref}[/green] added to the shared brain; every agent reads it from now on."
    )


@brain_app.command("export")
def brain_export(
    workspace: WorkspaceOption = None,
    out: Annotated[
        Path | None, typer.Option(help="Where to write the vault. Defaults to <workspace>/brain.")
    ] = None,
) -> None:
    """Read the inbox and render the vault now, without waiting for a wake."""
    from aurelis.brain.vault import sync_brain

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        export = sync_brain(runtime, root=out)
    finally:
        runtime.close()
    console.print(escape(export.describe()))
    console.print(f"[dim]Open {escape(str(export.root))} as a vault in Obsidian.[/dim]")
