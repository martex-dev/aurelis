"""``aurelis mission`` — opening, inspecting and running a mission.

The M2 demonstration lives here: one mission, one project, three agents whose
tasks sequence themselves through dependencies rather than through an
orchestrator.

Progress is printed the way the company computes it — successes, failures and
budget refusals side by side. There is deliberately no single percentage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from aurelis.comms.tables import MessageKind
from aurelis.core.enums import TaskStatus
from aurelis.intel.briefing import TASK_KIND as BRIEFING_TASK
from aurelis.meetings.ceremonies import (
    close_out,
    hold_kickoff,
    hold_retrospective,
    kickoff_meeting_ref,
)
from aurelis.missions.pipeline import Step, plan_project
from aurelis.missions.states import MissionState, ProjectState
from aurelis.platform.db.tables import Task
from aurelis.research.triage import QUESTION_TASK, TRIAGE_TASK
from aurelis.runtime import Runtime

console = Console()

mission_app = typer.Typer(help="Missions, projects and the work under them.", no_args_is_help=True)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_STATUS_COLOUR = {
    TaskStatus.SUCCEEDED: "green",
    TaskStatus.FAILED: "red",
    TaskStatus.CANCELLED: "yellow",
    TaskStatus.REFUSED_BUDGET: "yellow",
    TaskStatus.QUEUED: "dim",
    TaskStatus.CLAIMED: "cyan",
}


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@mission_app.command("run")
def mission_run(
    workspace: WorkspaceOption = None,
    objective: Annotated[
        str, typer.Option(help="What the mission is for.")
    ] = "Review the crypto desk and decide whether anything there is worth studying",
    symbol: Annotated[str | None, typer.Option(help="Symbol to work on.")] = None,
    max_turns: Annotated[int, typer.Option(help="Safety bound on the loop.")] = 12,
) -> None:
    """Open a mission, plan it, and run it to completion.

    Three agents, three dependent tasks, no orchestrator: INTEL briefs the
    desk, QUANT reads that briefing and asks a question, LEAD-R decides
    whether it earns a project. Each waits for the one before because the
    queue will not hand out a task whose dependency has not succeeded.
    """
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        runtime.staff()

        with runtime.database.session() as session:
            intel = runtime.roster.by_handle(session, "INTEL")
            quant = runtime.roster.by_handle(session, "QUANT")
            lead = runtime.roster.by_handle(session, "LEAD-R")
            ops = runtime.roster.by_handle(session, "OPS")
            for agent in (intel, quant, lead, ops):
                runtime.worker.open_daily_budget(session, agent, tokens=100_000)

            mission = runtime.missions.open_mission(
                session,
                objective=objective,
                owner_agent=runtime.roster.by_handle(session, "CIO").ref,
                departments=("market_intelligence", "quantitative_research"),
                desks=("crypto",),
                budget_tokens=60_000,
            )

            # The gate: PLANNING -> ACTIVE is refused until a kickoff
            # exists. At M3 a real meeting produces it.
            ceremony = hold_kickoff(
                session,
                chair=runtime.chair,
                missions=runtime.missions,
                roster=runtime.roster,
                subject_ref=mission.ref,
                participants=(intel.ref, quant.ref, lead.ref),
                chair_ref=ops.ref,
                desk="crypto",
                evidence={
                    "desk": "crypto",
                    "data": "fixture (offline, not a market simulation)",
                },
            )
            kickoff = ceremony.meeting
            runtime.missions.transition(session, mission.ref, MissionState.ACTIVE)

            project = runtime.missions.open_project(
                session,
                mission_ref=mission.ref,
                name="Crypto desk review",
                intent="One briefing, one independent check, one triage decision.",
                lead_agent=lead.ref,
                desk="crypto",
                budget_tokens=40_000,
            )
            runtime.missions.record_kickoff(
                session,
                subject_ref=project.ref,
                plan="Brief, question, triage.",
                participants=(intel.ref, quant.ref, lead.ref),
            )
            runtime.missions.transition(session, project.ref, ProjectState.ACTIVE)
            chair_ref = ops.ref

            payload: dict[str, object] = {"bars": 48}
            if symbol:
                payload["symbol"] = symbol

            plan_project(
                session,
                runtime.missions,
                runtime.queue,
                project_ref=project.ref,
                steps=(
                    Step(BRIEFING_TASK, intel.ref, dict(payload), name="brief"),
                    Step(
                        QUESTION_TASK,
                        quant.ref,
                        {**payload, "bars": 96, "ask": lead.ref},
                        after=("brief",),
                        name="question",
                    ),
                    Step(TRIAGE_TASK, lead.ref, {}, after=("question",), name="triage"),
                ),
            )
            mission_ref = mission.ref
            project_ref = project.ref
            actors = [intel.ref, quant.ref, lead.ref]

        # Turn by turn. Each pass gives every agent a chance; the dependency
        # graph decides who can actually do anything.
        turns = []
        for _ in range(max_turns):
            progressed = False
            with runtime.database.session() as session:
                runtime.queue.cancel_stranded(session)
                for ref in actors:
                    agent = runtime.roster.get(session, ref)
                    result = runtime.worker.run_once(session, agent)
                    if result is not None:
                        turns.append(result)
                        progressed = True
            if not progressed:
                break

        # The mission closes the way it opened: with a meeting. Both levels
        # need one -- the rule applies to projects as well, which is why the
        # project cannot close on the mission's retrospective.
        with runtime.database.session() as session:
            hold_retrospective(
                session,
                chair=runtime.chair,
                missions=runtime.missions,
                roster=runtime.roster,
                scorer=runtime.forecasts,
                subject_ref=project_ref,
                participants=(actors[0], actors[1], actors[2]),
                chair_ref=chair_ref,
                desk="crypto",
            )
            close_out(session, runtime.missions, project_ref)
            retro = hold_retrospective(
                session,
                chair=runtime.chair,
                missions=runtime.missions,
                roster=runtime.roster,
                scorer=runtime.forecasts,
                subject_ref=mission_ref,
                participants=(actors[0], actors[1], actors[2]),
                chair_ref=chair_ref,
                kickoff_meeting_ref=kickoff_meeting_ref(session, mission_ref),
                desk="crypto",
            ).meeting
            close_out(session, runtime.missions, mission_ref)

        with runtime.database.session() as session:
            progress = runtime.missions.progress(session, mission_ref)
            spent = runtime.missions.spent(session, mission_ref)
            messages = runtime.comms.read(
                session, channel_id="desk-crypto", agent_ref=actors[2], limit=10
            )
            calibration = runtime.forecasts.company_calibration(session)
            verification = runtime.ledger.verify(session)
    finally:
        runtime.close()

    for message in messages:
        console.print(
            Panel(
                escape(message.body),
                title=f"[bold]{escape(message.from_agent)}[/bold] · "
                f"{escape(MessageKind(message.kind).value)} · {escape(message.subject)}",
                subtitle=f"[dim]cites {len(message.evidence_refs)} source(s)[/dim]",
                border_style="dim",
            )
        )

    table = Table(show_header=False, box=None)
    table.add_column("", style="bold", width=14)
    table.add_column("")
    table.add_row("mission", mission_ref)
    table.add_row("kickoff", f"{kickoff.ref} — {kickoff.describe()}")
    table.add_row("turns", str(len(turns)))
    table.add_row("progress", progress.describe())
    table.add_row("retrospective", f"{retro.ref} — {retro.describe()}")
    if calibration:
        table.add_row(
            "calibration", "; ".join(c.describe() for c in calibration[:3])
        )
    table.add_row("tokens", f"{spent.tokens:,}")
    table.add_row("cost", f"${spent.usd:.6f}")
    table.add_row(
        "chain",
        f"[green]{verification.describe()}[/green]"
        if verification.ok
        else f"[red]{verification.describe()}[/red]",
    )
    console.print(table)

    if progress.succeeded != progress.total or not verification.ok:
        raise typer.Exit(code=1)
    console.print(
        "\n[green]M3 acceptance: opened and closed with meetings; "
        "every claim sourced.[/green]"
    )


@mission_app.command("list")
def mission_list(workspace: WorkspaceOption = None) -> None:
    """Every mission and how it is actually going."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = [
                (m, runtime.missions.progress(session, m.ref))
                for m in runtime.missions.missions(session)
            ]
    finally:
        runtime.close()

    if not rows:
        console.print("[dim]No missions yet. Run [bold]aurelis mission run[/bold].[/dim]")
        return

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("ref", width=9)
    table.add_column("state", width=11)
    table.add_column("progress", width=34)
    table.add_column("objective", overflow="fold")
    for mission, progress in rows:
        table.add_row(mission.ref, mission.state, progress.describe(), mission.objective)
    console.print(table)


@mission_app.command("show")
def mission_show(
    ref: Annotated[str, typer.Argument(help="Mission reference, e.g. MSN-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """One mission: its projects, its work, and every task's outcome."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            try:
                mission = runtime.missions.mission(session, ref.upper())
            except KeyError:
                console.print(f"[red]No mission {escape(ref)!r}.[/red]")
                raise typer.Exit(code=1) from None

            progress = runtime.missions.progress(session, mission.ref)
            spent = runtime.missions.spent(session, mission.ref)
            projects = runtime.missions.projects(session, mission.ref)
            layout = []
            for project in projects:
                items = runtime.missions.work_items(session, project.ref)
                tasks = []
                for item in items:
                    task = session.execute(
                        sa.select(Task).where(Task.ref == item.task_ref)
                    ).scalar_one()
                    tasks.append((task, runtime.queue.blocked_by(session, task.ref)))
                layout.append((project, tasks))
    finally:
        runtime.close()

    console.print(
        f"\n[bold]{mission.ref}[/bold]  [dim]{mission.state}[/dim]\n{mission.objective}\n"
    )
    console.print(f"  kickoff        {mission.kickoff_ref or '[red]none — cannot start[/red]'}")
    console.print(
        f"  retrospective  {mission.retrospective_ref or '[dim]none — cannot close[/dim]'}"
    )
    console.print(f"  progress       {progress.describe()}")
    console.print(f"  spent          {spent.tokens:,} tokens, ${spent.usd:.6f}\n")

    for project, tasks in layout:
        console.print(f"[bold]{project.ref}[/bold]  {project.name}  [dim]{project.state}[/dim]")
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("task", width=10)
        table.add_column("kind", width=20)
        table.add_column("assignee", width=9)
        table.add_column("status", width=15)
        table.add_column("waiting on", overflow="fold")
        for task, blocked in tasks:
            colour = _STATUS_COLOUR.get(TaskStatus(task.status), "white")
            table.add_row(
                task.ref,
                task.kind,
                task.assignee or "—",
                f"[{colour}]{task.status}[/{colour}]",
                ", ".join(blocked) or "[dim]—[/dim]",
            )
        console.print(table)
        console.print()
