"""``aurelis org`` and ``aurelis agent`` — looking at the company.

Everything here reads. The station will render all of it properly at M7; until
then these commands are how an operator sees who works here, what each of them
may do, and what they have actually done.

The permission views matter most. Being able to ask "what can this agent see,
write and invoke?" and get an answer from the record — rather than from a
diagram — is what makes the separation of duty checkable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.agents.roster import StaffedAgent
from aurelis.agents.tools import registered_tools
from aurelis.org.charters import CHARTERS
from aurelis.org.departments import DEPARTMENTS
from aurelis.org.desks import DESKS
from aurelis.runtime import Runtime

console = Console()

org_app = typer.Typer(help="The organization: departments, desks, charters.", no_args_is_help=True)
agent_app = typer.Typer(help="Agents: who works here and what they may do.", no_args_is_help=True)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@org_app.command("show")
def org_show() -> None:
    """The org chart as it exists in code."""
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("department", style="bold", width=26)
    table.add_column("charters", justify="right", width=8)
    table.add_column("head", width=28)
    table.add_column("owns", overflow="fold")

    for spec in DEPARTMENTS.values():
        held = [c for c in CHARTERS.values() if c.department is spec.department]
        table.add_row(
            spec.name,
            str(len(held)),
            CHARTERS[spec.head_charter].name,
            spec.owns,
        )
    console.print(table)

    deterministic = sum(1 for c in CHARTERS.values() if c.deterministic)
    console.print(
        f"\n[bold]{len(CHARTERS)}[/bold] charters across "
        f"[bold]{len(DEPARTMENTS)}[/bold] departments; "
        f"[bold]{deterministic}[/bold] are deterministic and cost nothing to run."
    )


@org_app.command("desks")
def org_desks() -> None:
    """Market desks and whether they are open."""
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("desk", style="bold", width=14)
    table.add_column("status", width=10)
    table.add_column("opens", width=7)
    table.add_column("engines", width=12)
    table.add_column("instruments", overflow="fold")

    for desk, spec in DESKS.items():
        colour = "green" if spec.status.value == "active" else "dim"
        table.add_row(
            desk.value,
            f"[{colour}]{spec.status.value}[/{colour}]",
            spec.opens_at_milestone or "—",
            ", ".join(spec.engines),
            ", ".join(spec.instruments),
        )
    console.print(table)


@org_app.command("charters")
def org_charters(
    department: Annotated[
        str | None, typer.Option("--department", "-d", help="Filter by department.")
    ] = None,
) -> None:
    """Every charter, its tier, and what it may write."""
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("#", justify="right", width=4)
    table.add_column("charter", style="bold", width=30)
    table.add_column("tier", width=6)
    table.add_column("writes", overflow="fold")

    for spec in sorted(CHARTERS.values(), key=lambda c: c.number):
        if department and spec.department.value != department:
            continue
        table.add_row(
            str(spec.number),
            spec.charter_id,
            "[dim]none[/dim]" if spec.tier.value == "none" else spec.tier.value,
            ", ".join(sorted(s.value for s in spec.write_scopes)) or "[dim]—[/dim]",
        )
    console.print(table)


@agent_app.command("hire")
def agent_hire(workspace: WorkspaceOption = None) -> None:
    """Staff the company from the launch roster. Idempotent."""
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        hired = runtime.staff()
        with runtime.database.session() as session:
            everyone = runtime.roster.all(session)
    finally:
        runtime.close()

    console.print(f"[green]{hired}[/green] agent(s) on the roster.\n")
    _print_roster(everyone)


@agent_app.command("list")
def agent_list(workspace: WorkspaceOption = None) -> None:
    """Who works here."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            everyone = runtime.roster.all(session)
    finally:
        runtime.close()

    if not everyone:
        console.print("[dim]Nobody hired yet. Run [bold]aurelis agent hire[/bold].[/dim]")
        return
    _print_roster(everyone)


def _print_roster(everyone: list[StaffedAgent]) -> None:
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("ref", width=8)
    table.add_column("handle", style="bold", width=8)
    table.add_column("department", width=24)
    table.add_column("desk", width=9)
    table.add_column("tier", width=5)
    table.add_column("state", width=9)
    table.add_column("holds", justify="right", width=6)

    for agent in everyone:
        table.add_row(
            agent.ref,
            agent.handle,
            agent.department.value,
            agent.desk.value if agent.desk else "[dim]—[/dim]",
            agent.authority.tier.value,
            agent.state.value,
            str(len(agent.coverage)),
        )
    console.print(table)
    total = sum(len(a.coverage) for a in everyone)
    console.print(
        f"\n[dim]{len(everyone)} agents holding {total} charters. "
        "Generalists stand in for specialists until the evidence justifies a split.[/dim]"
    )


@agent_app.command("show")
def agent_show(
    handle: Annotated[str, typer.Argument(help="Agent handle, e.g. INTEL.")],
    workspace: WorkspaceOption = None,
) -> None:
    """One agent: what it holds, what it may see, write and invoke."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            try:
                agent = runtime.roster.by_handle(session, handle.upper())
            except KeyError:
                console.print(f"[red]No agent with handle {escape(handle)!r}.[/red]")
                raise typer.Exit(code=1) from None
    finally:
        runtime.close()

    authority = agent.authority
    console.print(
        f"\n[bold]{agent.ref} · {agent.handle}[/bold]  "
        f"[dim]{agent.department.value}"
        f"{' · ' + agent.desk.value if agent.desk else ''} · "
        f"{authority.seniority.value} · tier {authority.tier.value} · "
        f"{agent.state.value}[/dim]\n"
    )

    charters = Table(show_header=True, header_style="bold", box=None)
    charters.add_column("holds charter", style="bold", width=32)
    charters.add_column("remit", overflow="fold")
    for charter_id in agent.coverage:
        spec = CHARTERS[charter_id]
        charters.add_row(f"{spec.number:>2}  {spec.name}", spec.remit)
    console.print(charters)

    implemented = registered_tools()
    console.print("\n[bold]CAN SEE[/bold]")
    console.print("  " + ", ".join(sorted(v.value for v in authority.read_views)))
    console.print("\n[bold]CAN WRITE[/bold]")
    console.print("  " + ", ".join(sorted(s.value for s in authority.write_scopes)))
    console.print("\n[bold]CAN INVOKE[/bold]")
    for tool in sorted(authority.tools, key=lambda t: t.value):
        mark = (
            "" if tool in implemented else "  [dim](not implemented yet)[/dim]"
        )
        console.print(f"  {tool.value}{mark}")
    console.print()
