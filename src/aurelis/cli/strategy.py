"""``aurelis strategy`` — what the company built, and how much of it is its own.

The commands here are shaped by the distinction the layer exists to hold: a
strategy is *composed* from authored pieces, so ``components`` and ``novelty``
are first-class views rather than diagnostics. "How much of this did we write?"
should take one command to answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.org.desks import Desk
from aurelis.runtime import Runtime
from aurelis.strategy.markets import profile
from aurelis.strategy.states import Portability
from aurelis.strategy.tables import Component, Strategy, StrategyVersion

console = Console()

strategy_app = typer.Typer(
    help="Strategies: components, compositions, gates, portability.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_PORTABILITY_TONE = {
    Portability.NATIVE.value: "green",
    Portability.PORTED.value: "green",
    Portability.UNPROVEN.value: "yellow",
    Portability.REFUTED_HERE.value: "red",
    Portability.INAPPLICABLE.value: "dim",
}


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@strategy_app.command("list")
def strategy_list(workspace: WorkspaceOption = None) -> None:
    """Every strategy, its state and its current version."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = list(
                session.execute(sa.select(Strategy).order_by(Strategy.ref)).scalars()
            )
        if not rows:
            console.print("[yellow]no strategies[/yellow]")
            return
        table = Table(title="strategies")
        for column in ("ref", "name", "desk", "state", "version", "thesis"):
            table.add_column(column)
        for row in rows:
            table.add_row(
                row.ref,
                row.name,
                row.desk,
                row.state,
                row.current_version or "—",
                row.thesis[:60],
            )
        console.print(table)
    finally:
        runtime.close()


@strategy_app.command("components")
def strategy_components(
    workspace: WorkspaceOption = None,
    desk: Annotated[
        str | None, typer.Option(help="Filter by the desk it was authored for.")
    ] = None,
) -> None:
    """Every authored component, and where it came from.

    The origin column is the point: it separates what this company invented
    from what it adapted, and every row cites something a reader can follow.
    """
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            query = sa.select(Component).order_by(Component.ref)
            if desk:
                query = query.where(Component.desk == desk)
            rows = list(session.execute(query).scalars())

        if not rows:
            console.print("[yellow]no components authored[/yellow]")
            return
        table = Table(title="components")
        for column in ("ref", "kind", "name", "origin", "cites", "desk", "assumes"):
            table.add_column(column)
        for row in rows:
            tone = "green" if row.origin in ("invented", "derived_from_failure") else "dim"
            table.add_row(
                row.ref,
                row.kind,
                row.name,
                f"[{tone}]{row.origin}[/{tone}]",
                row.origin_ref,
                row.desk,
                ", ".join(str(item) for item in row.assumes) or "—",
            )
        console.print(table)
        console.print(
            "[dim]green origins are work this company authored; dim ones are "
            "adapted or refined from something else[/dim]"
        )
    finally:
        runtime.close()


@strategy_app.command("show")
def strategy_show(
    version_ref: Annotated[str, typer.Argument(help="Version reference, e.g. SV-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """One version: what it is made of, how it got here, and where it works."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            version = session.execute(
                sa.select(StrategyVersion).where(StrategyVersion.ref == version_ref)
            ).scalar_one_or_none()
            if version is None:
                console.print(f"[red]no version {escape(version_ref)}[/red]")
                raise typer.Exit(2)

            components = runtime.synthesis.components_of(session, version_ref)
            novelty = runtime.synthesis.novelty(session, version_ref)
            lineage = runtime.synthesis.lineage_of(session, version_ref)
            ancestry = runtime.synthesis.ancestry(session, version_ref)
            portability = runtime.strategies.portability(session, version_ref)
            report = runtime.gates.report(session, version_ref)

        console.print(f"[bold]{escape(version.ref)}[/bold]  {escape(version.state)}")
        console.print(f"  strategy   {escape(version.strategy_ref)} (v{version.n})")
        console.print(f"  desk       {escape(version.desk)}")
        console.print(f"  digest     {escape(version.spec_digest[:32])}")
        if version.promoted_at:
            console.print(
                f"  promoted   {version.promoted_at:%Y-%m-%d %H:%M} "
                f"by {escape(version.promoted_by_meeting or '—')} [dim](frozen)[/dim]"
            )

        console.print("\n[bold]Composed from[/bold]")
        for component in components:
            console.print(
                f"  {component.ref}  {component.kind:8} {component.name}  "
                f"[dim]{component.origin} <- {component.origin_ref}[/dim]"
            )
        console.print(f"\n  {escape(novelty.describe())}")

        console.print("\n[bold]Known weaknesses, stated by the authors[/bold]")
        for weakness in version.known_weaknesses:
            console.print(f"  - {escape(str(weakness))}")

        if len(ancestry) > 1:
            console.print("\n[bold]Ancestry[/bold]")
            console.print("  " + escape(" -> ".join(ancestry)))
        if lineage:
            console.print("\n[bold]Lineage[/bold]")
            for entry in lineage:
                console.print(
                    f"  {entry.act:10} {escape(entry.detail[:80])} "
                    f"[dim]{entry.author}[/dim]"
                )

        console.print("\n[bold]Gates[/bold]")
        console.print("  " + escape(report.describe()).replace("\n", "\n  "))

        console.print("\n[bold]Where this has actually been measured[/bold]")
        for row in portability:
            tone = _PORTABILITY_TONE.get(row.status, "dim")
            reason = f" — {row.reason[:60]}" if row.reason else ""
            console.print(
                f"  {row.desk:12} [{tone}]{row.status}[/{tone}]{escape(reason)}"
            )
    finally:
        runtime.close()


@strategy_app.command("markets")
def strategy_markets(workspace: WorkspaceOption = None) -> None:
    """What each of the seven desks structurally provides.

    Derived from the desk registry, so it cannot drift from the org chart.
    """
    runtime = _runtime(workspace)
    try:
        table = Table(title="market profiles")
        table.add_column("desk")
        table.add_column("calendar")
        table.add_column("provides")
        for desk in Desk:
            market = profile(desk)
            table.add_row(
                market.name,
                market.calendar,
                ", ".join(sorted(item.value for item in market.provides)),
            )
        console.print(table)
        console.print(
            "[dim]A component declaring an assumption a desk does not provide "
            "is inapplicable there — a category error, not an untested idea[/dim]"
        )
    finally:
        runtime.close()


@strategy_app.command("author")
def strategy_author(
    workspace: WorkspaceOption = None,
    desk: Annotated[str, typer.Option(help="Which desk to author for.")] = "crypto",
    agent: Annotated[str, typer.Option(help="Which agent takes the seat.")] = "STRAT",
) -> None:
    """Put an agent in the author's seat and measure what it designs.

    The agent chooses a whole strategy from a closed space, in its own words,
    before anything has been run on the data it will be scored against — and
    the company preregisters the **whole space it chose from**, not the one
    design it picked.

    The reasoner behind the seat in this repository is a deterministic stand-in,
    not a model, and every desk runs on fixtures rather than market data. What
    this exercises is the machinery.
    """
    from aurelis.authoring.attempt import CAVEAT, run_authoring
    from aurelis.authoring.design import space_size
    from aurelis.authoring.standin import scripted_author
    from aurelis.core.config import load_settings
    from aurelis.platform.llm.providers import MockProvider

    settings = load_settings(home=workspace) if workspace else load_settings()
    runtime = Runtime.build(settings, provider=MockProvider(responder=scripted_author))
    try:
        runtime.initialise()
        runtime.staff()
        outcome = run_authoring(runtime, desk=Desk(desk), agent_handle=agent)
        with runtime.database.session() as session:
            verification = runtime.ledger.verify(session)
    finally:
        runtime.close()

    authored = outcome.authored
    console.print()
    console.print(
        f"[bold]{authored.version_ref}[/bold]  authored by {authored.agent_ref} "
        f"on the {authored.desk.value} desk"
    )
    console.print(f"[dim]{escape(authored.design.describe())}[/dim]")
    console.print()

    choices = Table(title=f"what the agent chose — 1 of {space_size()} reachable designs")
    for column in ("slot", "chose", "in its own words"):
        choices.add_column(column, overflow="fold")
    for turn in authored.turns:
        choices.add_row(
            turn.slot,
            ", ".join(turn.chosen) or "-",
            escape(turn.reasoning[:110]),
        )
    console.print(choices)

    measured = Table(title="what the measurement said")
    measured.add_column("", style="bold", width=18)
    measured.add_column("")
    tone = "yellow" if outcome.verdict.value != "confirmed" else "green"
    measured.add_row("verdict", f"[{tone}]{outcome.verdict.value.upper()}[/{tone}]")
    measured.add_row("reason", escape(outcome.reason))
    for name, value in outcome.metrics.items():
        measured.add_row(name, value)
    for base in outcome.baselines:
        measured.add_row(f"baseline {base.kind}", f"total return {base.total_return}")
    measured.add_row(
        "beat the baselines",
        "[green]yes[/green]" if outcome.beat_baselines else "[red]no[/red]",
    )
    measured.add_row("declared cells", f"{outcome.declared_cells} (the whole space)")
    measured.add_row("trials in family", str(outcome.trials_in_family))
    if outcome.shortfall:
        measured.add_row(
            "power",
            f"{outcome.bars} bars run, {outcome.bars_required} needed "
            f"({outcome.years_required} years) to settle the claim",
        )
    measured.add_row("origin", f"{authored.origin.value} citing {authored.origin_ref}")
    if authored.novelty is not None:
        measured.add_row("novelty", escape(authored.novelty.describe()))
    measured.add_row(
        "chain",
        f"[green]{verification.describe()}[/green]"
        if verification.ok
        else f"[red]{verification.describe()}[/red]",
    )
    console.print(measured)

    if not outcome.beat_baselines:
        console.print()
        console.print(
            "[yellow]The authored design did not beat holding the asset.[/yellow] "
            "A rule that cannot beat buying and holding has not found anything, "
            "and one that cannot beat doing nothing has found less. That is the "
            "result, and it is reported rather than tuned away."
        )
    console.print()
    console.print(f"[dim]{escape(CAVEAT)}[/dim]")
