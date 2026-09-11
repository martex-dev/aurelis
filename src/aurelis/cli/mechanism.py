"""``aurelis mechanism`` — the join from a mined conjunction to a tested scheme."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

mechanism_app = typer.Typer(
    help="Mechanisms: an agent's causal story over a mined pattern, tested forward.",
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
    from aurelis.mechanism.standin import scripted_discovery
    from aurelis.platform.llm.seating import seat_provider

    return Runtime.build(settings, provider=seat_provider(settings, scripted_discovery))


@mechanism_app.command("discover")
def mechanism_discover(
    workspace: WorkspaceOption = None,
    agent: Annotated[str, typer.Option(help="Which agent takes the seat.")] = "QUANT",
    trigger: Annotated[str, typer.Option(help="Trigger event kind.")] = "price.volume_spike",
    then: Annotated[str, typer.Option(help="Second event kind.")] = "price.range_break",
    hours: Annotated[int, typer.Option(help="Co-occurrence window, hours.")] = 24,
) -> None:
    """Show an agent a mined co-occurrence and seal the mechanism it states.

    The mechanism's predictions on every other occurrence are generated at once,
    sealed before their outcomes, and scored later. Offline this seats a
    deterministic stand-in and says so.
    """
    from aurelis.mechanism.discovery import seat_discovery
    from aurelis.mechanism.predictions import generate_predictions
    from aurelis.platform.llm.seating import stands_in

    runtime = _runtime(workspace, seated=True)
    try:
        runtime.initialise()
        runtime.staff()
        mechanism = seat_discovery(
            runtime, agent_handle=agent, trigger_kind=trigger, second_kind=then, window_hours=hours
        )
        if mechanism is None:
            console.print(
                "[yellow]No mechanism stated.[/yellow] Either the pattern was not "
                "found, or the agent declined to give a causal reason for it."
            )
            return
        with runtime.database.session() as session:
            run = generate_predictions(session, mechanism)
            status = runtime.mechanisms.status(session, mechanism.ref)
        provider = runtime.settings.provider
    finally:
        runtime.close()

    console.print()
    console.print(f"[bold]{mechanism.ref}[/bold]  {escape(mechanism.title)}")
    table = Table(show_header=False)
    table.add_column("", style="bold", width=14)
    table.add_column("", overflow="fold")
    table.add_row(
        "trigger",
        f"{mechanism.trigger_kind} -> {mechanism.direction} over {mechanism.horizon_hours}h",
    )
    table.add_row("confidence", str(mechanism.confidence))
    table.add_row("why", escape(mechanism.why))
    table.add_row("other side", escape(mechanism.other_side))
    table.add_row("decay", escape(mechanism.decay))
    table.add_row("found on", f"{mechanism.found_on_instrument}")
    table.add_row("predictions", f"{status.predictions} sealed, {status.scored} scored")
    console.print(table)
    console.print(f"[dim]{escape(run.describe())}[/dim]")
    if stands_in(provider):
        console.print(
            "\n[dim]What sat in the seat is a deterministic stand-in, not a model. "
            "It always predicts up, so on a fixture its out-of-sample record will "
            "not beat the base rate and the sweep will retire it.[/dim]"
        )
    console.print(
        "[dim]A mechanism is a candidate scheme only when its out-of-sample "
        "predictions beat a coin toss and the base rate. Until then it is "
        "gathering evidence, one sealed prediction at a time.[/dim]"
    )


@mechanism_app.command("list")
def mechanism_list(workspace: WorkspaceOption = None) -> None:
    """Every mechanism, and what its out-of-sample predictions say so far."""
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            statuses = runtime.mechanisms.statuses(session)
    finally:
        runtime.close()
    table = Table(title="mechanisms")
    for column in (
        "ref",
        "title",
        "trigger",
        "predictions",
        "scored",
        "brier",
        "base rate",
        "verdict",
    ):
        table.add_column(column, overflow="fold")
    for status in statuses:
        m = status.mechanism
        cal = status.calibration
        tone = "green" if status.is_scheme else ("red" if status.retired else "yellow")
        table.add_row(
            m.ref,
            escape(m.title[:40]),
            m.trigger_kind,
            str(status.predictions),
            str(status.scored),
            str(cal.mean_brier) if cal.mean_brier is not None else "—",
            str(cal.base_rate_brier) if cal.base_rate_brier is not None else "—",
            f"[{tone}]{escape(status.verdict)}[/{tone}]",
        )
    console.print(table)
    if not statuses:
        console.print("[dim]no mechanism stated yet: `aurelis mechanism discover`[/dim]")
    console.print(
        "\n[dim]The training occurrence is excluded from every score: a mechanism "
        "scored on the instance that suggested it is scored on the data that "
        "suggested it. Only the additional predictions count.[/dim]"
    )


@mechanism_app.command("sweep")
def mechanism_sweep(workspace: WorkspaceOption = None) -> None:
    """Retire mechanisms that gathered enough predictions and did not beat the base rate."""
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            retired = runtime.mechanisms.sweep_retirements(session)
    finally:
        runtime.close()
    if not retired:
        console.print("[dim]nothing retired: no mechanism has failed with enough evidence[/dim]")
        return
    for row in retired:
        console.print(f"[red]{row.ref}[/red] retired: {escape(row.retired_reason)}")


@mechanism_app.command("mine")
def mechanism_mine(
    workspace: WorkspaceOption = None,
    hours: Annotated[int, typer.Option(help="Co-occurrence window, hours.")] = 24,
    min_count: Annotated[int, typer.Option(help="Least occurrences to list.")] = 3,
) -> None:
    """Rank the conjunctions in the event stream. A list, not a discovery."""
    import datetime as dt

    from aurelis.mechanism.mining import mine_pairs

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            pairs = mine_pairs(session, within=dt.timedelta(hours=hours), min_count=min_count)
    finally:
        runtime.close()
    table = Table(title=f"conjunctions within {hours}h")
    for column in ("trigger", "then", "count", "instruments"):
        table.add_column(column)
    for pair in pairs:
        table.add_row(pair.first, pair.second, str(pair.count), str(pair.instruments))
    console.print(table)
    console.print(
        "[dim]Every row is a coincidence until an agent states why it works and the "
        "predictions it implies come true. `aurelis mechanism discover --trigger ... "
        "--then ...` puts one to an agent; `aurelis run` puts all of them to everyone.[/dim]"
    )


@mechanism_app.command("trades")
def mechanism_trades(workspace: WorkspaceOption = None) -> None:
    """What each candidate scheme did on paper: round trips and realised P&L."""
    from aurelis.mechanism.paper import pnl_of

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            rows = [
                (s.mechanism, pnl_of(session, s.mechanism.ref))
                for s in runtime.mechanisms.statuses(session)
            ]
    finally:
        runtime.close()
    table = Table(title="scheme paper trading")
    for column in ("ref", "title", "trades", "open", "closed", "won", "realised P&L"):
        table.add_column(column, overflow="fold")
    for mechanism, summary in rows:
        tone = "green" if summary["pnl"] > 0 else ("red" if summary["pnl"] < 0 else "dim")
        table.add_row(
            mechanism.ref,
            escape(mechanism.title[:40]),
            str(summary["trades"]),
            str(summary["open"]),
            str(summary["closed"]),
            str(summary["won"]),
            f"[{tone}]{summary['pnl']}[/{tone}]",
        )
    console.print(table)
    console.print(
        "[dim]Only a candidate scheme trades, and only on paper, through Risk. P&L is "
        "reported and never judged: over a short window it is mostly luck. The "
        "calibration record is the measure.[/dim]"
    )
