"""``aurelis evolution`` — how each agent forms views, and how that is changing."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

evolution_app = typer.Typer(
    help="Evolution: each agent's method, its forward fitness, and replacements.",
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
    from aurelis.platform.llm.seating import seat_provider, standins

    return Runtime.build(settings, provider=seat_provider(settings, standins()))


@evolution_app.command("status")
def evolution_status(workspace: WorkspaceOption = None) -> None:
    """Every judging agent's current method and how its views have scored under it."""
    from aurelis.autonomy.agenda import _judges
    from aurelis.evolution.methods import current_method, fitness_of

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            rows = []
            for agent in _judges(session):
                fit = fitness_of(session, agent.ref)
                method = current_method(session, agent.ref)
                rows.append(
                    (
                        agent.ref,
                        agent.handle,
                        f"v{method.version} by {method.authored_by}" if method else "charter",
                        str(fit.views),
                        str(fit.brier) if fit.brier is not None else "-",
                        str(fit.error) if fit.error is not None else "-",
                        fit.verdict,
                        (method.text[:90] if method else ""),
                    )
                )
    finally:
        runtime.close()
    table = Table(title="methods and their forward fitness")
    for column in ("agent", "handle", "method", "views", "brier", "std err", "verdict", "text"):
        table.add_column(column, overflow="fold")
    for row in rows:
        table.add_row(*(escape(c) for c in row))
    console.print(table)
    console.print(
        "[dim]Fitness is the Brier score of the views an agent sealed under its current "
        "method, against 0.25 for a coin toss. A method more than one standard error "
        "worse, over at least 20 views, is replaced once a day.[/dim]"
    )


@evolution_app.command("run")
def evolution_run(workspace: WorkspaceOption = None) -> None:
    """Measure every method now and replace the failing ones. Offline, a stand-in writes."""
    from aurelis.evolution.methods import evolve

    runtime = _runtime(workspace, seated=True)
    try:
        runtime.initialise()
        runtime.staff()
        run = evolve(runtime)
    finally:
        runtime.close()
    console.print(escape(run.describe()))
