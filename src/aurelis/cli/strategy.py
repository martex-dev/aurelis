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
