"""``aurelis run`` — the company works on itself until it runs out of things to do.

The distinction from `aurelis tick` is worth stating plainly. `tick` advances
the working day: due jobs fire, stranded work clears, every agent gets a turn.
It does not decide what the day is *for*. This does: it asks the company's own
mandate what is missing, takes the first action that could move one, checks
whether it did, and stops when nothing is left.
"""

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

run_app = typer.Typer(
    help="Let the company decide its own next action, bounded.",
    no_args_is_help=False,
    invoke_without_command=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]


@run_app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    workspace: WorkspaceOption = None,
    cycles: Annotated[int, typer.Option(help="How many decisions it may take.")] = 8,
    calls: Annotated[int, typer.Option(help="Model-call budget for the run.")] = 60,
    snapshot: Annotated[
        str, typer.Option(help="Measure research on this recorded market.")
    ] = "",
) -> None:
    """Take turns until there is nothing left worth doing.

    Every cycle: assess the mandate, choose the first action that could move
    something unmet, run it, and check whether it moved. An action that has
    already been taken is not taken again — repeating a search widens it, which
    raises the bar the result has to clear rather than helping it.

    The loop does not fetch data and cannot trade. Fetching reaches outside the
    company and needs a person; there is no live broker adapter to reach for.
    """
    if ctx.invoked_subcommand is not None:  # pragma: no cover - no subcommands yet
        return

    from aurelis.autonomy.loop import run_autonomy
    from aurelis.core.config import load_settings
    from aurelis.platform.llm.seating import seat_provider, standins

    settings = load_settings(home=workspace) if workspace else load_settings()
    runtime = Runtime.build(settings, provider=seat_provider(settings, standins()))
    try:
        runtime.initialise()
        runtime.staff()
        source = _source(runtime, snapshot) if snapshot else None
        outcome = run_autonomy(
            runtime, cycles=cycles, calls=calls, source=source
        )
        with runtime.database.session() as session:
            verification = runtime.ledger.verify(session)
    finally:
        runtime.close()

    console.print()
    console.print(
        f"[bold]{escape(outcome.run_ref)}[/bold]  "
        f"{len(outcome.acted)} action(s) over {len(outcome.cycles)} cycle(s), "
        f"{outcome.calls} model call(s)"
    )
    console.print()

    walk = Table(title="what the company decided to do")
    for column in ("#", "action", "outcome", "moved", "what happened"):
        walk.add_column(column, overflow="fold")
    for record in outcome.cycles:
        if record.action is None:
            walk.add_row(str(record.n), "—", "stopped", "—", escape(record.reason))
            continue
        tone = {"acted": "green", "failed": "red", "refused": "yellow"}.get(
            record.outcome, "yellow"
        )
        walk.add_row(
            str(record.n),
            record.action,
            f"[{tone}]{record.outcome}[/{tone}]",
            "[green]yes[/green]" if record.moved else "no",
            escape(record.detail[:150]),
        )
    console.print(walk)

    if outcome.gained:
        console.print(
            f"\n[green]conditions gained:[/green] {', '.join(sorted(outcome.gained))}"
        )
    else:
        console.print(
            "\n[yellow]no condition moved.[/yellow] Every action that ran did "
            "what it does and the standard still says not yet — which is a "
            "result about the research, not a failure of the loop."
        )

    left = Table(title="what is left, and why the company cannot act on it")
    for column in ("condition", "why"):
        left.add_column(column, overflow="fold")
    for condition, why in sorted(outcome.stuck.items()):
        if why == "actionable":
            continue
        left.add_row(condition, escape(why))
    if left.row_count:
        console.print()
        console.print(left)

    console.print()
    console.print(f"[dim]stopped: {escape(outcome.stopped_because)}[/dim]")
    console.print(
        f"[dim]chain: {escape(verification.describe())}[/dim]"
        if verification.ok
        else f"[red]chain: {escape(verification.describe())}[/red]"
    )


def _source(runtime: Runtime, ref: str) -> object:
    from aurelis.intel.snapshots import MarketSnapshot, SnapshotSource
    from aurelis.trading.paper import held_out

    with runtime.database.session() as session:
        row = session.execute(
            sa.select(MarketSnapshot).where(MarketSnapshot.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            console.print(f"[red]no snapshot {escape(ref)}[/red]")
            raise typer.Exit(2)
        research = held_out(row.bars)
        source = SnapshotSource(session, row, upto=research)
    console.print(
        f"[dim]researching on {escape(row.ref)}: {research} of {row.bars} bars, "
        f"{row.bars - research} held back for a forward walk[/dim]"
    )
    return source
