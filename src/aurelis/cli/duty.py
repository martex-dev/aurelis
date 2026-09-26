"""``aurelis duty`` — each department's daily duty, who holds it, and when it last ran."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

duty_app = typer.Typer(
    help="Duties: the audit, integrity, health, lesson and memo each department runs daily.",
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


@duty_app.command("list")
def duty_list(workspace: WorkspaceOption = None) -> None:
    """Every duty, the agent who holds it, when it last ran, and whether it is due."""
    from aurelis.autonomy.duties import DUTIES, duty_due, holder, last_done

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        now = runtime.clock.now()
        with runtime.database.session() as session:
            rows = []
            for duty in DUTIES:
                agent = holder(session, duty)
                last = last_done(session, duty.key)
                rows.append(
                    (
                        duty.key,
                        f"{agent.handle} ({agent.ref})" if agent is not None else "nobody",
                        f"{last:%Y-%m-%d %H:%M}Z" if last else "never",
                        "yes" if duty_due(session, duty, now) else "no",
                        str(duty.calls),
                        duty.intent,
                    )
                )
    finally:
        runtime.close()
    table = Table(title="daily duties")
    for column in ("duty", "held by", "last ran", "due", "model calls", "what it does"):
        table.add_column(column, overflow="fold")
    for row in rows:
        table.add_row(*(escape(cell) for cell in row))
    console.print(table)


@duty_app.command("run")
def duty_run(
    workspace: WorkspaceOption = None,
    only: Annotated[
        list[str] | None, typer.Option("--only", help="Run just this duty; repeatable.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Run even if it already ran in the last day.")
    ] = False,
) -> None:
    """Run the due duties now, instead of waiting for the wake. At most two model calls."""
    from aurelis.autonomy.duties import run_duties

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        results = run_duties(runtime, only=tuple(only or ()), force=force)
    finally:
        runtime.close()
    if not results:
        console.print("Nothing due. `--force` runs a duty again inside its day.")
    for result in results:
        console.print(escape(result.describe()))
