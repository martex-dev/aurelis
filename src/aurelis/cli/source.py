"""``aurelis source`` — the free catalogue, and what the agents asked to read."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

source_app = typer.Typer(
    help="Sources: the free, official, keyless catalogue and the agents' choices.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]


def _runtime(workspace: Path | None, *, seated: bool = False) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    if not seated:
        return Runtime.build(settings)
    from aurelis.platform.llm.seating import seat_provider, standins

    return Runtime.build(settings, provider=seat_provider(settings, standins()))


@source_app.command("catalogue")
def source_catalogue() -> None:
    """Every source the company could read. All free, official, keyless."""
    from aurelis.intel.news import CATALOGUE

    table = Table(title="free source catalogue")
    for column in ("name", "kind", "cost", "key", "covers", "url"):
        table.add_column(column, overflow="fold")
    for source in CATALOGUE.values():
        table.add_row(
            source.name, source.kind, source.cost, source.key, escape(source.covers), source.url
        )
    console.print(table)
    console.print(
        "[dim]A source is in the catalogue only if it is an official feed that needs no "
        "key and costs nothing. Which of them the company reads is an agent's "
        "decision: `aurelis source seat`.[/dim]"
    )


@source_app.command("requests")
def source_requests(workspace: WorkspaceOption = None) -> None:
    """What the agents asked the company to read, and why."""
    from aurelis.sources.seat import active_sources
    from aurelis.sources.tables import SourceRequest

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            rows = list(
                session.execute(
                    sa.select(SourceRequest).order_by(SourceRequest.requested_at.desc())
                ).scalars()
            )
            active = active_sources(session)
    finally:
        runtime.close()
    table = Table(title="source requests")
    for column in ("ref", "at", "agent", "source", "wanted", "because"):
        table.add_column(column, overflow="fold")
    for r in rows:
        table.add_row(
            r.ref,
            r.requested_at.strftime("%m-%d %H:%M"),
            r.agent_ref,
            r.source,
            "[green]yes[/green]" if r.wanted else "[dim]no[/dim]",
            escape(r.reason[:120]),
        )
    console.print(table)
    console.print(
        f"[dim]read every wake under a news grant: {', '.join(active) or 'nothing yet'}[/dim]"
    )


@source_app.command("seat")
def source_seat(
    workspace: WorkspaceOption = None,
    agent: Annotated[str, typer.Option(help="Which agent chooses.")] = "NEWS",
) -> None:
    """Show one agent the catalogue and record what it asks for. Offline, a stand-in."""
    from aurelis.platform.llm.seating import stands_in
    from aurelis.sources.seat import SourceRefused, seat_sources

    runtime = _runtime(workspace, seated=True)
    try:
        runtime.initialise()
        runtime.staff()
        try:
            rows = seat_sources(runtime, agent_handle=agent)
        except SourceRefused as error:
            console.print(f"[red]{escape(agent)} was refused: {escape(str(error))}[/red]")
            raise typer.Exit(code=1) from None
        provider = runtime.settings.provider
    finally:
        runtime.close()
    wanted = [r.source for r in rows if r.wanted]
    if wanted:
        console.print(f"[green]{escape(agent)}[/green] asked for {', '.join(wanted)}")
    else:
        console.print(f"[yellow]{escape(agent)}[/yellow] wants none of the catalogue")
    console.print(f"[dim]because: {escape(rows[0].reason)}[/dim]")
    if stands_in(provider):
        console.print("[dim]What sat in the seat is a deterministic stand-in, not a model.[/dim]")
