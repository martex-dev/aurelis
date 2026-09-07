"""``aurelis desk`` — the seven desks, and what each of them is.

``compare`` is the command worth having: it puts the same measurement from
every desk side by side, converted through each desk's own calendar, and prints
the conversion factor next to each figure so a reader can undo it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.desks.calendars import CALENDARS, calendar_for
from aurelis.desks.costs import costs_for
from aurelis.desks.limits import limits_for
from aurelis.desks.power import required_observations
from aurelis.desks.readiness import Readiness, assess
from aurelis.desks.sources import live_feed_status
from aurelis.org.desks import DESKS, Desk
from aurelis.runtime import Runtime

console = Console()

desk_app = typer.Typer(
    help="The seven market desks: clocks, cost models, limits, and readiness.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_STATE = {
    Readiness.PASS: "[green]pass[/green]",
    Readiness.PROVISIONAL: "[yellow]provisional[/yellow]",
    Readiness.FAIL: "[red]fail[/red]",
}

_FIXTURE_CAVEAT = (
    "[dim]Every desk runs on fixture data: deterministic, offline, and not a "
    "market. No live feed is wired for any of them, and no research conclusion "
    "about a real market may be drawn from anything they produce.[/dim]"
)


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@desk_app.command("list")
def desk_list() -> None:
    """Every desk: its clock, its costs, and what bounds it."""
    table = Table(title="the seven desks")
    for column in ("desk", "calendar", "bars/yr", "round trip", "material size", "gross", "short"):
        table.add_column(column)
    for desk, spec in DESKS.items():
        calendar = calendar_for(desk.value)
        costs = costs_for(desk)
        limits = limits_for(desk)
        table.add_row(
            spec.name,
            calendar.name,
            f"{calendar.periods_per_year('1h')}",
            f"{costs.round_trip_bps}bps",
            f"${costs.liquidity.material_size_usd:,}",
            f"{limits.max_gross_leverage}x",
            "yes" if costs.liquidity.shortable else "[yellow]no[/yellow]",
        )
    console.print(table)
    console.print(
        "[dim]A round trip costs 40bps on crypto and 760 on memecoins. That "
        "single column is what most strategies on this company's most "
        "expensive desk will fail on.[/dim]"
    )
    console.print(_FIXTURE_CAVEAT)


@desk_app.command("show")
def desk_show(
    desk_name: Annotated[str, typer.Argument(help="Desk, e.g. equities.")],
) -> None:
    """One desk in full: readiness, costs, limits, universe."""
    try:
        desk = Desk(desk_name)
    except ValueError:
        console.print(
            f"[red]no desk {escape(desk_name)}[/red]; there are "
            f"{escape(', '.join(d.value for d in Desk))}"
        )
        raise typer.Exit(2) from None

    spec = DESKS[desk]
    calendar = calendar_for(desk.value)
    costs = costs_for(desk)
    limits = limits_for(desk)

    console.print(f"[bold]{escape(spec.name)}[/bold]  ({desk.value})")
    console.print(f"  instruments  {escape(', '.join(spec.instruments))}")
    console.print(f"  calendar     {escape(calendar.describe())}")
    console.print(
        f"  clock        {calendar.periods_per_year('1h')} hourly bars a year; "
        f"a per-bar Sharpe is multiplied by "
        f"{calendar.annualisation('1h').quantize(Decimal('0.01'))}"
    )
    console.print(f"  costs        {escape(costs.describe())}")
    console.print(f"  [dim]{escape(costs.basis)}[/dim]")
    console.print(f"  limits       {escape(limits.describe())}")
    console.print(f"  [dim]{escape(limits.rationale)}[/dim]")

    assessment = assess(desk)
    table = Table(title="readiness")
    for column in ("check", "state", "detail"):
        table.add_column(column)
    for item in assessment.items:
        table.add_row(item.name, _STATE[item.state], item.detail)
    console.print(table)
    console.print(
        f"[{'green' if assessment.may_open else 'red'}]"
        f"{escape(assessment.describe())}[/]"
    )


@desk_app.command("calendars")
def desk_calendars() -> None:
    """The four clocks, and what they do to a Sharpe ratio."""
    table = Table(title="trading calendars")
    for column in ("calendar", "sessions", "hours", "1h bars/yr", "1d bars/yr", "sqrt(1h)"):
        table.add_column(column)
    for calendar in CALENDARS.values():
        table.add_row(
            calendar.name,
            str(calendar.sessions_per_year),
            str(calendar.hours_per_session),
            str(calendar.periods_per_year("1h")),
            str(calendar.periods.get("1d", "—")),
            str(calendar.annualisation("1h").quantize(Decimal("0.01"))),
        )
    console.print(table)
    console.print(
        "[dim]The last column is the whole reason this module exists. The same "
        "per-bar Sharpe is worth 2.31x more on a 24/7 desk than on the NYSE, "
        "and an archive that ranked them unconverted would be ranking by "
        "sampling frequency.[/dim]"
    )


@desk_app.command("power")
def desk_power(
    claim: Annotated[str, typer.Option(help="Annualised Sharpe being claimed.")] = "1.0",
    bars: Annotated[int, typer.Option(help="Bars available per desk.")] = 2190,
) -> None:
    """How much data each desk needs to settle the same annualised claim."""
    table = Table(title=f"data required to settle an annualised Sharpe of {claim}")
    for column in ("desk", "per-bar effect", "bars needed", "years", "have", "powered"):
        table.add_column(column)
    years: set[str] = set()
    for desk in DESKS:
        need = required_observations(
            desk.value,
            annualised_claim=Decimal(claim),
            interval="1h",
            bars_available=bars,
        )
        years.add(str(need.years_required))
        table.add_row(
            desk.value,
            str(need.per_bar_effect),
            f"{need.bars_required:,}",
            str(need.years_required),
            f"{need.bars_available:,}",
            "[green]yes[/green]" if need.powered else "[red]no[/red]",
        )
    console.print(table)
    if len(years) == 1:
        console.print(
            f"\n[bold]The same {years.pop()} years on every desk[/bold] — and a "
            "different number of bars on each."
        )
    console.print(
        "[dim]A research budget stated in bars is not a budget. The same "
        "number gives crypto seven weeks and equities nine months, and "
        "underpowers whichever desk samples fastest while looking "
        "even-handed.[/dim]"
    )


@desk_app.command("feeds")
def desk_feeds() -> None:
    """Which desks have live market data. None of them do."""
    table = Table(title="data feeds")
    for column in ("desk", "status"):
        table.add_column(column)
    for desk, status in live_feed_status().items():
        table.add_row(desk, status)
    console.print(table)
    console.print(
        "[yellow]No desk in this repository is connected to a live market "
        "feed.[/yellow] [dim]The declared sources are named in the desk "
        "registry so the work is legible; none is wired.[/dim]"
    )


@desk_app.command("open")
def desk_open(
    desk_name: Annotated[str, typer.Argument(help="Desk, or 'all'.")] = "all",
    workspace: WorkspaceOption = None,
) -> None:
    """Run the checklist and open a desk, or refuse with the reasons."""
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            if desk_name == "all":
                opened = runtime.desks.open_all(session)
            else:
                opened = (runtime.desks.open(session, desk_name),)
        for entry in opened:
            console.print(f"[green]opened[/green] {escape(entry.describe())}")
            for caveat in entry.caveats:
                console.print(f"    [yellow]caveat[/yellow] {escape(caveat)}")
    finally:
        runtime.close()


@desk_app.command("compare")
def desk_compare(
    workspace: WorkspaceOption = None,
    span: Annotated[str, typer.Option(help="Research budget, in years.")] = "0.25",
) -> None:
    """Run the same mission on all seven desks and compare the results."""
    from aurelis.desks.demonstration import run_multi_desk

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        runtime.staff()
        outcome = run_multi_desk(runtime, span=Decimal(span))
    finally:
        runtime.close()

    table = Table(title=f"the same claim, on seven desks, over {span} years each")
    for column in ("desk", "verdict", "raw sharpe", "x", "annualised", "return", "bars"):
        table.add_column(column)
    for result in outcome.results:
        converted = result.annualised
        tone = "green" if result.verdict.value == "confirmed" else "dim"
        table.add_row(
            result.desk.value,
            f"[{tone}]{result.verdict.value}[/{tone}]",
            f"{result.raw_sharpe:+.6f}",
            str(converted.factor.quantize(Decimal("0.01"))) if converted else "—",
            f"{converted.value:+.4f}" if converted else "[dim]—[/dim]",
            f"{result.total_return:+.4f}",
            f"{result.power.bars_available:,}/{result.power.bars_required:,}",
        )
    console.print(table)

    console.print(f"\n  raw order         {escape(', '.join(outcome.ranking_raw))}")
    console.print(f"  annualised order  {escape(', '.join(outcome.ranking_annualised))}")
    console.print(
        f"  [{'yellow' if outcome.reordered else 'dim'}]"
        f"{'the order changes' if outcome.reordered else 'the order happens not to change'}"
        "[/]"
    )
    console.print(f"\n[bold]Distortion[/bold]  {escape(outcome.distortion)}")
    console.print(f"[bold]Budget[/bold]      {escape(outcome.budget_finding)}")

    if outcome.refusals:
        console.print("\n[bold]Comparisons refused[/bold]")
        for refusal in outcome.refusals:
            console.print(f"  [dim]{escape(refusal)}[/dim]")
    console.print()
    console.print(_FIXTURE_CAVEAT)


__all__ = ["desk_app"]
