"""``aurelis mandate`` — the standard, the answer, and the record of asking.

The company does not get a live adapter switched on for it. It measures itself
against ten conditions it declared in advance and answers in one of two words,
and only a yes interrupts anybody.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.mandate.assessment import assess, history
from aurelis.mandate.standard import STANDARD, digest
from aurelis.runtime import Runtime

console = Console()

mandate_app = typer.Typer(
    help="Whether the company believes it is ready to trade real money.",
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


@mandate_app.command("standard")
def mandate_standard() -> None:
    """The conditions, and why each one is there.

    Declared in advance and hashed. A bar lowered after it was missed would
    make everything else worthless, so the digest travels on every assessment
    and a change to it shows up in the history.
    """
    table = Table(title=f"the standard — digest {digest()[:16]}")
    for column in ("#", "condition", "asks", "why"):
        table.add_column(column, overflow="fold")
    for index, criterion in enumerate(STANDARD, 1):
        table.add_row(
            str(index),
            criterion.key,
            escape(criterion.asks),
            escape(criterion.why),
        )
    console.print(table)

    blocked = [c for c in STANDARD if c.blocked]
    if blocked:
        console.print()
        console.print(
            f"[yellow]{len(blocked)} of these cannot be satisfied by research "
            "today[/yellow] — the machinery to produce the evidence does not "
            "exist yet:"
        )
        for criterion in blocked:
            console.print(f"  [bold]{criterion.key}[/bold] — {escape(criterion.blocked_by)}")


@mandate_app.command("assess")
def mandate_assess(
    workspace: WorkspaceOption = None,
    escalate_to: Annotated[
        str, typer.Option(help="Who is told, if the answer is yes.")
    ] = "OPERATOR",
) -> None:
    """Check the company against the standard, and record the answer.

    Written down whichever way it goes. Only a `ready` escalates: a system that
    pinged its owner every time it looked would train them to stop reading.
    """
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        outcome = assess(runtime, escalate_to=escalate_to)
    finally:
        runtime.close()

    table = Table(title=f"{outcome.ref} — against standard {outcome.standard_digest[:16]}")
    for column in ("", "condition", "what the record says"):
        table.add_column(column, overflow="fold")
    for finding in outcome.findings:
        if finding.met:
            mark = "[green]MET[/green]"
        elif finding.blocked:
            mark = "[red]BLOCKED[/red]"
        else:
            mark = "[yellow]unmet[/yellow]"
        table.add_row(mark, finding.criterion.key, escape(finding.reading))
    console.print(table)

    console.print()
    if outcome.ready:
        console.print(
            f"[bold green]READY[/bold green] — all {len(outcome.findings)} "
            f"conditions met. Escalated to {outcome.escalated_to}."
        )
        console.print(
            "The company is asking you to consider funding a live account. "
            "Every condition above is a row in its own record; none of it is "
            "self-assessment."
        )
    else:
        console.print(
            f"[bold yellow]NOT YET[/bold yellow] — {len(outcome.met)} of "
            f"{len(outcome.findings)} conditions met. Nobody was interrupted."
        )

    if outcome.blocked:
        console.print()
        console.print(
            "[red]Blocked — no amount of research would satisfy these:[/red]"
        )
        for finding in outcome.blocked:
            console.print(
                f"  [bold]{finding.criterion.key}[/bold] — "
                f"{escape(finding.criterion.blocked_by)}"
            )
        console.print(
            "[dim]That is the difference between a result and a to-do list, and "
            "it is the company's own answer to what to build next.[/dim]"
        )

    if outcome.standard_changed:
        console.print()
        console.print(
            f"[red]The standard changed since the last assessment[/red] "
            f"({outcome.previous_digest[:16] if outcome.previous_digest else ''} "
            f"-> {outcome.standard_digest[:16]}). A bar that moved after it was "
            "missed is the one change that would make this worthless — read the "
            "diff before reading the verdict."
        )


@mandate_app.command("history")
def mandate_history(workspace: WorkspaceOption = None) -> None:
    """Every time the company asked itself, newest first.

    The refusals are the point. A company that kept only the assessment that
    passed could not show the bar had ever held.
    """
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = history(session)
    finally:
        runtime.close()

    if not rows:
        console.print("[dim]The company has never assessed itself.[/dim]")
        return

    table = Table(title="mandate assessments")
    for column in ("ref", "when", "verdict", "met", "blocked", "standard", "told"):
        table.add_column(column)
    digests = {str(row.standard_digest) for row in rows}
    for row in rows:
        tone = "green" if row.verdict == "ready" else "yellow"
        table.add_row(
            row.ref,
            row.assessed_at.strftime("%Y-%m-%d %H:%M"),
            f"[{tone}]{row.verdict}[/{tone}]",
            f"{row.met}/{row.criteria}",
            str(row.blocked),
            str(row.standard_digest)[:12],
            row.escalated_to or "—",
        )
    console.print(table)
    if len(digests) > 1:
        console.print()
        console.print(
            f"[red]{len(digests)} different standards appear above.[/red] The "
            "bar moved between assessments; compare them before comparing the "
            "verdicts."
        )
