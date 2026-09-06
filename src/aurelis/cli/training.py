"""``aurelis training`` — the scenario suite, the scores, and the gate.

``regression`` is the command that matters: it is what CI runs, and it exits
non-zero when a revised playbook catches fewer real defects than the one it
would replace. Everything else here is a way of reading the same measurement.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.engines.synthetic.scenarios import CATALOGUE, scenario
from aurelis.engines.synthetic.truth import Presence
from aurelis.runtime import Runtime
from aurelis.training.playbook import INCUMBENT, playbook_for, specialty_of
from aurelis.training.regression import gate
from aurelis.training.tables import ScenarioMark, TrainingRun

console = Console()

training_app = typer.Typer(
    help="Training scenarios: planted defects, scores, and the playbook gate.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_CAVEAT = (
    "[dim]Institutional competence on planted effects, not market truth. An "
    "agent calibrated here may still be miscalibrated on a real market.[/dim]"
)


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@training_app.command("scenarios")
def training_scenarios() -> None:
    """The catalogue: what each world has planted in it, before measurement."""
    table = Table(title="training scenarios (author's intent, not the answer key)")
    for column in ("id", "title", "effect", "planted", "universe"):
        table.add_column(column)
    for scen in CATALOGUE:
        table.add_row(
            scen.scenario_id,
            scen.title,
            "yes" if scen.intended_effect else "[dim]nothing[/dim]",
            ", ".join(sorted(d.value for d in scen.intended_defects)) or "[dim]—[/dim]",
            "point-in-time" if scen.point_in_time else "[yellow]survivors only[/yellow]",
        )
    console.print(table)
    console.print(
        "[dim]Intent is not the answer key. What a scenario really contains is "
        "measured by replication — see `aurelis training truth`.[/dim]"
    )


@training_app.command("truth")
def training_truth(
    scenario_id: Annotated[str, typer.Option(help="Just this one.")] = "",
) -> None:
    """What replication established, and where it disagreed with the author."""
    from aurelis.engines.synthetic.truth import Bench

    bench = Bench()
    chosen = [scenario(scenario_id)] if scenario_id else list(CATALOGUE)
    table = Table(title="measured truth")
    for column in ("id", "effect", "reading", "defect", "presence", "reading "):
        table.add_column(column)
    surprises: list[str] = []
    for scen in chosen:
        truth = bench.truth(scen)
        rows = sorted(truth.defects, key=lambda d: d.value)
        table.add_row(
            scen.scenario_id,
            _tone(truth.effect_present),
            truth.effect.describe(),
            "",
            "",
            "",
        )
        for defect in rows:
            table.add_row(
                "",
                "",
                "",
                defect.value,
                _tone(truth.presence(defect)),
                truth.defects[defect].describe(),
            )
        surprises.extend(f"{scen.scenario_id}: {line}" for line in truth.surprises())
    console.print(table)
    if surprises:
        console.print("\n[bold yellow]Plants that did not take[/bold yellow]")
        for line in surprises:
            console.print(f"  {escape(line)}")
        console.print(
            "[dim]Reported, not reconciled. A catalogue that edited its intent "
            "to match its measurements would stop being a check on anything.[/dim]"
        )


@training_app.command("suite")
def training_suite(
    charters: Annotated[
        str, typer.Option(help="Comma-separated charter ids to score as a specialty.")
    ] = "",
) -> None:
    """Run a playbook over every scenario and mark it."""
    from aurelis.training.suite import TrainingSuite

    coverage = tuple(c.strip() for c in charters.split(",") if c.strip())
    playbook = playbook_for(coverage) if coverage else INCUMBENT
    if playbook is None:
        console.print(
            f"[yellow]{escape(', '.join(coverage))} has no scenario specialty; "
            "nothing in the suite questions it[/yellow]"
        )
        raise typer.Exit(0)

    suite = TrainingSuite()
    result = suite.run(playbook)
    table = Table(title=f"{playbook.describe()} over {len(CATALOGUE)} scenarios")
    for column in ("scenario", "effect call", "caught", "missed", "false alarm", "unscored"):
        table.add_column(column)
    for row in result.marks:
        table.add_row(
            row.scenario_id,
            {"correct": "[green]correct[/green]", "wrong": "[red]wrong[/red]"}.get(
                row.effect_call, "[dim]unscored[/dim]"
            ),
            ", ".join(sorted(d.value for d in row.caught)) or "—",
            ", ".join(sorted(d.value for d in row.missed)) or "—",
            ", ".join(sorted(d.value for d in row.false_alarms)) or "—",
            ", ".join(sorted(d.value for d in row.unscored)) or "—",
        )
    console.print(table)
    score = result.score
    console.print(
        f"\n  catch rate       {_rate(score.catch_rate)}  "
        f"({score.caught}/{score.planted} real defects raised)"
    )
    console.print(
        f"  false alarm rate {_rate(score.false_alarm_rate)}  "
        f"({score.false_alarms}/{score.false_alarms + score.true_silences})"
    )
    console.print(
        f"  effect calls     {_rate(score.effect_accuracy)}  "
        f"({score.effect_correct}/{score.effect_correct + score.effect_wrong})"
    )
    holes = suite.unscorable()
    if holes:
        console.print(
            f"\n[yellow]No scenario currently measures "
            f"{escape(', '.join(sorted(d.value for d in holes)))}.[/yellow] "
            "[dim]A gap in the catalogue, not a property of the procedure.[/dim]"
        )
    console.print(_CAVEAT)


@training_app.command("record")
def training_record(
    agent_ref: Annotated[str, typer.Argument(help="Agent, e.g. AG-0009.")],
    workspace: WorkspaceOption = None,
) -> None:
    """An agent's training record: the score it started work on."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            run = runtime.onboarding.latest(session, agent_ref)
            if run is None:
                console.print(f"[yellow]{escape(agent_ref)} has no training record[/yellow]")
                raise typer.Exit(0)
            marks = list(
                session.execute(
                    sa.select(ScenarioMark)
                    .where(ScenarioMark.run_ref == run.ref)
                    .order_by(ScenarioMark.scenario_id)
                ).scalars()
            )
        tone = {"passed": "green", "failed": "red"}.get(run.verdict, "yellow")
        console.print(
            f"[bold]{escape(run.ref)}[/bold]  {escape(agent_ref)}  "
            f"[{tone}]{run.verdict.upper()}[/{tone}]"
        )
        console.print(f"  {escape(run.reason)}")
        console.print(
            f"  procedure  {escape(run.playbook_id)}@{escape(run.playbook_version)}"
        )
        console.print(f"  specialty  {escape(', '.join(run.specialty)) or '—'}")
        console.print(
            f"  worlds     {run.scenarios} scenarios, {run.replications} replications"
        )
        console.print(f"  catalogue  {escape(run.catalogue_digest[:16])}")
        if marks:
            table = Table(title="per scenario")
            for column in ("scenario", "effect", "caught", "missed", "false alarm"):
                table.add_column(column)
            for row in marks:
                table.add_row(
                    row.scenario_id,
                    row.effect_call,
                    ", ".join(row.caught) or "—",
                    ", ".join(row.missed) or "—",
                    ", ".join(row.false_alarms) or "—",
                )
            console.print(table)
        console.print(_CAVEAT)
    finally:
        runtime.close()


@training_app.command("roster")
def training_roster(workspace: WorkspaceOption = None) -> None:
    """Every agent's starting record, side by side."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = list(
                session.execute(
                    sa.select(TrainingRun).order_by(TrainingRun.agent_ref)
                ).scalars()
            )
        if not rows:
            console.print("[yellow]nobody has been scored yet[/yellow]")
            return
        table = Table(title="training records")
        for column in ("agent", "verdict", "specialty", "caught", "false alarms", "why"):
            table.add_column(column)
        for row in rows:
            tone = {"passed": "green", "failed": "red"}.get(row.verdict, "yellow")
            table.add_row(
                row.agent_ref,
                f"[{tone}]{row.verdict}[/{tone}]",
                ", ".join(row.specialty) or "[dim]none[/dim]",
                f"{row.caught}/{row.caught + row.missed}" if row.specialty else "—",
                str(row.false_alarms) if row.specialty else "—",
                row.reason[:60],
            )
        console.print(table)
        console.print(_CAVEAT)
    finally:
        runtime.close()


@training_app.command("regression")
def training_regression(
    defect: Annotated[
        str, typer.Option(help="Blunt this defect's check, to prove the gate bites.")
    ] = "",
    degradation: Annotated[str, typer.Option(help="The revised threshold.")] = "5",
) -> None:
    """Gate a revised playbook against the incumbent. CI runs this.

    With no options it checks the shipped playbook against itself, which must
    always pass — that is the guard against the gate silently breaking. With
    ``--defect`` it blunts one check, which must always fail.
    """
    from aurelis.meetings.types import ObjectionType

    candidate = INCUMBENT
    if defect:
        try:
            target = ObjectionType(defect)
        except ValueError:
            console.print(f"[red]no defect type {escape(defect)}[/red]")
            raise typer.Exit(2) from None
        candidate = INCUMBENT.revised(target, degradation=Decimal(degradation))

    verdict = gate(candidate)
    table = Table(title="playbook regression")
    for column in ("", "incumbent", "candidate"):
        table.add_column(column)
    before, after = verdict.incumbent.score, verdict.candidate.score
    table.add_row("procedure", verdict.incumbent.playbook, verdict.candidate.playbook)
    table.add_row("real defects caught", str(before.caught), str(after.caught))
    table.add_row("missed", str(before.missed), str(after.missed))
    table.add_row("false alarms", str(before.false_alarms), str(after.false_alarms))
    table.add_row(
        "effect calls right", str(before.effect_correct), str(after.effect_correct)
    )
    console.print(table)

    if verdict.ships:
        console.print(f"[green]{escape(verdict.describe())}[/green]")
        return
    console.print(f"[red]{escape(verdict.describe())}[/red]")
    console.print(
        "[dim]Counts, not rates: a revision that narrowed its checks could "
        "improve every rate while finding less.[/dim]"
    )
    raise typer.Exit(1)


def _tone(presence: Presence) -> str:
    return {
        Presence.PRESENT: "[green]present[/green]",
        Presence.ABSENT: "[dim]absent[/dim]",
        Presence.UNDETERMINED: "[yellow]undetermined[/yellow]",
    }[presence]


def _rate(value: Decimal | None) -> str:
    return "[dim]NOT SCORED[/dim]" if value is None else str(value)


__all__ = ["training_app", "specialty_of"]
