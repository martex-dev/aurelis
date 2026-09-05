"""``aurelis station`` — serve the facility, seal a snapshot, check the drawing."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from aurelis.runtime import Runtime
from aurelis.station.app import serve
from aurelis.station.build import build_sealed
from aurelis.station.layout import build_facility
from aurelis.station.projections import room_statuses
from aurelis.station.render import render_facility
from aurelis.station.svg import collisions

console = Console()

station_app = typer.Typer(
    help="Mission Control: the facility, the timeline, the sealed snapshot.",
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


@station_app.command("serve")
def station_serve(
    workspace: WorkspaceOption = None,
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8787,
    host: Annotated[
        str,
        typer.Option(
            help=(
                "Interface to bind. Loopback by default — the station has no "
                "authentication and shows every unpublished result."
            )
        ),
    ] = "127.0.0.1",
) -> None:
    """Run the live station until interrupted.

    Read-only: the handler implements GET and nothing else, so there is no
    route through which the station can change the record.
    """
    runtime = _runtime(workspace)
    if host not in ("127.0.0.1", "localhost", "::1"):
        console.print(
            f"[yellow]Binding to {escape(host)}. The station has no "
            "authentication and exposes every meeting, permission and "
            "unpublished result to anyone who can reach this port.[/yellow]"
        )
    console.print(f"Mission Control on [bold]http://{escape(host)}:{port}/[/bold]")
    console.print("[dim]Ctrl-C to stop. Read-only; nothing here writes.[/dim]")
    try:
        serve(runtime, host=host, port=port)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        console.print("stopped")
    finally:
        runtime.close()


@station_app.command("build")
def station_build(
    workspace: WorkspaceOption = None,
    out: Annotated[
        Path | None, typer.Option(help="Output file. Defaults to <workspace>/station.html.")
    ] = None,
) -> None:
    """Write a sealed snapshot: one self-contained file, no external requests."""
    runtime = _runtime(workspace)
    try:
        target = out or (runtime.settings.workspace / "station.html")
        report = build_sealed(runtime, target)
        console.print(escape(report.describe()))
        if not report.chain_ok:
            raise typer.Exit(1)
    finally:
        runtime.close()


@station_app.command("check")
def station_check(workspace: WorkspaceOption = None) -> None:
    """Verify the drawing: no two captions may overlap.

    Overlapping text fails exactly where the facility is densest, which is
    where the information is. The check runs against the real occupancy, so a
    room whose status word grew can be caught before anyone looks at it.
    """
    runtime = _runtime(workspace)
    try:
        facility = build_facility()
        with runtime.database.session() as session:
            statuses = room_statuses(session)
        drawing = render_facility(facility, statuses)
        hits = collisions(drawing.labels)

        console.print(
            f"{len(drawing.labels)} label(s) measured across "
            f"{len(facility.rooms)} room(s) and {len(facility.bays)} bay(s)"
        )
        if not hits:
            console.print("[green]no overlapping captions[/green]")
            return
        for left, right in hits:
            console.print(
                f"[red]overlap[/red] {escape(left.content)!r} / {escape(right.content)!r}"
            )
        raise typer.Exit(1)
    finally:
        runtime.close()
