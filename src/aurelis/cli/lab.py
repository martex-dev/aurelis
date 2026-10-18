"""``aurelis lab``: every taught strategy, on every desk, tested honestly (M65)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

lab_app = typer.Typer(
    help="The strategy lab: classic strategies on years of data, after costs and luck.",
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


@lab_app.command("run")
def lab_run(workspace: WorkspaceOption = None) -> None:
    """Fetch the history and test the whole catalogue now. No model calls."""
    from aurelis.lab.run import lab_summary, run_lab

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        ref = run_lab(runtime)
        with runtime.database.session() as session:
            summary = lab_summary(session)
    finally:
        runtime.close()
    console.print(f"[bold]{ref}[/bold]")
    if summary is not None:
        console.print(escape(summary.line()))


@lab_app.command("show")
def lab_show(
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option("--limit", help="Rows of the best results to show.")] = 20,
) -> None:
    """The latest run: by desk, by family, and the best out-of-sample results."""
    import sqlalchemy as sa

    from aurelis.lab.run import lab_summary
    from aurelis.lab.tables import LabResult

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            summary = lab_summary(session)
            if summary is None:
                console.print("The lab has not run yet: `aurelis lab run`.")
                return
            rows = list(
                session.execute(
                    sa.select(LabResult)
                    .where(LabResult.run_ref == summary.ref)
                    .order_by(LabResult.oos_sharpe.desc())
                    .limit(limit)
                ).scalars()
            )
    finally:
        runtime.close()
    console.print(escape(summary.line()))
    families = Table(title="by family, over every market")
    for column in ("family", "tests", "survived", "mean OOS Sharpe", "beat holding %"):
        families.add_column(column)
    for name, (tests, survived) in sorted(summary.by_family.items()):
        sharpe, share = summary.family_oos.get(name, (0.0, 0.0))
        families.add_row(name, str(tests), str(survived), str(sharpe), str(share))
    console.print(families)
    best = Table(title=f"best {limit} out of sample (not a verdict: see the last column)")
    for column in (
        "strategy",
        "market",
        "IS Sharpe",
        "OOS Sharpe",
        "OOS return",
        "hold",
        "verdict",
    ):
        best.add_column(column, overflow="fold")
    for r in rows:
        best.add_row(
            escape(r.strategy),
            escape(r.symbol),
            str(r.is_sharpe),
            str(r.oos_sharpe),
            str(r.oos_return),
            str(r.oos_hold),
            escape(r.verdict),
        )
    console.print(best)
