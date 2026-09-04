"""``aurelis meeting`` — reading what the company said.

The transcript is a first-class object, so it gets a first-class view. Every
turn shows its speaker, its stance, and whether that speaker changed position;
the decision shows who dissented and why. The station renders all of it
properly at M7 — this is how you read it until then.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.meetings.tables import (
    ActionItem,
    Decision,
    Forecast,
    Meeting,
    MeetingObjection,
    MeetingParticipant,
    MeetingTurn,
)
from aurelis.runtime import Runtime

console = Console()

meeting_app = typer.Typer(
    help="Meetings: transcripts, decisions, calibration.", no_args_is_help=True
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_STANCE = {"supports": "green", "opposes": "red", "uncertain": "yellow", "abstains": "dim"}


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@meeting_app.command("list")
def meeting_list(workspace: WorkspaceOption = None) -> None:
    """Every meeting held, and whether it produced anything."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = session.execute(
                sa.select(Meeting).order_by(Meeting.convened_at)
            ).scalars().all()
    finally:
        runtime.close()

    if not rows:
        console.print("[dim]No meetings held yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("ref", width=10)
    table.add_column("type", width=16)
    table.add_column("chair", width=9)
    table.add_column("tokens", justify="right", width=7)
    table.add_column("outcome", width=16)
    table.add_column("subject", overflow="fold")
    for row in rows:
        verdict = (
            "[green]productive[/green]" if row.productive else "[yellow]unproductive[/yellow]"
        )
        if row.budget_exhausted:
            verdict += " [dim]budget[/dim]"
        table.add_row(row.ref, row.type, row.chair, str(row.tokens_spent), verdict, row.subject)
    console.print(table)

    unproductive = sum(1 for r in rows if not r.productive)
    console.print(
        f"\n[dim]{len(rows)} meeting(s); {unproductive} produced no state change. "
        "That number is a metric on the Chair and on the meeting type.[/dim]"
    )


@meeting_app.command("show")
def meeting_show(
    ref: Annotated[str, typer.Argument(help="Meeting reference, e.g. MTG-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """One meeting: the transcript, the objections, the decision, the dissent."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            meeting = session.execute(
                sa.select(Meeting).where(Meeting.ref == ref.upper())
            ).scalar_one_or_none()
            if meeting is None:
                console.print(f"[red]No meeting {escape(ref)!r}.[/red]")
                raise typer.Exit(code=1)

            turns = session.execute(
                sa.select(MeetingTurn)
                .where(MeetingTurn.meeting_ref == meeting.ref)
                .order_by(MeetingTurn.seq)
            ).scalars().all()
            forecasts = session.execute(
                sa.select(Forecast).where(Forecast.meeting_ref == meeting.ref)
            ).scalars().all()
            objections = session.execute(
                sa.select(MeetingObjection).where(MeetingObjection.meeting_ref == meeting.ref)
            ).scalars().all()
            decision = session.execute(
                sa.select(Decision).where(Decision.meeting_ref == meeting.ref)
            ).scalars().first()
            items = session.execute(
                sa.select(ActionItem).where(ActionItem.meeting_ref == meeting.ref)
            ).scalars().all()
            people = session.execute(
                sa.select(MeetingParticipant).where(
                    MeetingParticipant.meeting_ref == meeting.ref
                )
            ).scalars().all()
    finally:
        runtime.close()

    console.print(
        f"\n[bold]{meeting.ref}[/bold]  [dim]{meeting.type}, chaired by "
        f"{meeting.chair}, {meeting.tokens_spent}/{meeting.budget_tokens} tokens, "
        f"{meeting.rounds_used} exchange round(s)[/dim]\n{escape(meeting.subject)}\n"
    )
    console.print("  " + ", ".join(f"{p.agent_ref}[{p.attendance}]" for p in people) + "\n")

    if forecasts:
        console.print("[bold]FORECASTS[/bold]  [dim](recorded before anyone spoke)[/dim]")
        for f in forecasts:
            scored = (
                f"  -> outcome {f.outcome}, Brier {f.brier}"
                if f.scored_at is not None
                else "  [dim](unscored)[/dim]"
            )
            console.print(f"  {f.agent_ref}  P={f.probability}{scored}")
        console.print()

    console.print("[bold]TRANSCRIPT[/bold]")
    for turn in turns:
        colour = _STANCE.get(turn.stance, "white")
        changed = (
            f"  [yellow]changed from {turn.changed_mind_from}[/yellow]"
            if turn.changed_mind_from
            else ""
        )
        console.print(
            f"  [dim]{turn.seq:>2} {turn.phase:<9}[/dim] [bold]{escape(turn.speaker)}[/bold] "
            f"[{colour}]{turn.stance}[/{colour}]{changed}"
        )
        for line in escape(turn.body).splitlines()[:6]:
            console.print(f"       {line}")
    console.print()

    if objections:
        console.print("[bold]OBJECTIONS[/bold]")
        for o in objections:
            console.print(
                f"  {o.ref} [{o.severity}/{o.status}] {escape(o.statement)}\n"
                f"       [dim]{escape(str(o.test_result.get('detail', '')))}[/dim]"
            )
        console.print()

    if decision is not None:
        console.print("[bold]DECISION[/bold]")
        console.print(f"  {escape(decision.outcome)}")
        console.print(f"  [green]supporting[/green]: {', '.join(decision.supporting) or '-'}")
        if decision.dissent:
            for d in decision.dissent:
                console.print(
                    f"  [red]dissent[/red]: {d['agent']} - {escape(str(d['reason'])[:200])}"
                )
        else:
            console.print("  [dim]no dissent recorded[/dim]")
        console.print()

    if items:
        console.print("[bold]ACTION ITEMS[/bold]")
        for item in items:
            console.print(
                f"  {escape(item.description)} -> {item.owner}"
                + (f" [{item.task_ref}]" if item.task_ref else " [dim](no task)[/dim]")
            )
        console.print()


@meeting_app.command("calibration")
def meeting_calibration(workspace: WorkspaceOption = None) -> None:
    """How good the company's forecasts have been.

    Brier score; lower is better. 0.25 is what always saying 50% gets you, and
    an agent sitting at it is abstaining in numeric form rather than
    forecasting.
    """
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            records = runtime.forecasts.company_calibration(session)
    finally:
        runtime.close()

    if not records:
        console.print("[dim]No forecasts scored yet.[/dim]")
        return
    for record in records:
        colour = "green" if record.informative else "yellow"
        console.print(f"  [{colour}]{escape(record.describe())}[/{colour}]")
