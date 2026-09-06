"""``aurelis org`` — the company's measurements of itself, and its changes.

``develop`` is the command worth having. It runs two structural changes end to
end and prints both verdicts, one of which is a failure — which is the only way
to see that the measurement is doing anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.orgdev.detection import TRIGGERS, scan
from aurelis.orgdev.experiments import STANDING_QUESTIONS
from aurelis.orgdev.metrics import agent_metrics, charter_starvation, company_metrics
from aurelis.orgdev.states import EffectVerdict
from aurelis.orgdev.tables import CoverageTransfer, OrgChange, OrgExperiment
from aurelis.runtime import Runtime

console = Console()

orgdev_app = typer.Typer(
    help="Org development: metrics, triggers, changes, and experiments on the "
    "company's own shape.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_TONE = {
    "improved": "green",
    "partial": "yellow",
    "no_change": "yellow",
    "worse": "red",
    "unmeasurable": "dim",
}


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@orgdev_app.command("metrics")
def org_metrics(
    agent: Annotated[str, typer.Option(help="One agent, e.g. AG-0004.")] = "",
    workspace: WorkspaceOption = None,
) -> None:
    """What the company can measure about itself right now."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            if agent:
                measured = agent_metrics(session, agent)
                table = Table(title=f"{measured.handle} ({measured.agent_ref})")
                for column in ("metric", "value", "detail"):
                    table.add_column(column)
                for reading in measured.readings:
                    table.add_row(
                        reading.metric,
                        str(reading.value)
                        if reading.value is not None
                        else "[dim]NOT MEASURABLE[/dim]",
                        reading.detail,
                    )
                console.print(table)
                return

            table = Table(title="the company")
            for column in ("metric", "value", "detail"):
                table.add_column(column)
            for reading in company_metrics(session):
                table.add_row(
                    reading.metric,
                    str(reading.value)
                    if reading.value is not None
                    else "[dim]NOT MEASURABLE[/dim]",
                    reading.detail,
                )
            console.print(table)

            starvation = charter_starvation(session)
            orphaned = [c for c, w in starvation.items() if w.startswith("ORPHANED")]
            unattributable = sorted(
                c for c, w in starvation.items() if w.startswith("unattrib")
            )
            if orphaned:
                console.print(
                    f"[red]{len(orphaned)} charter(s) held by nobody[/red]: "
                    f"{escape(', '.join(sorted(orphaned)))}"
                )
            console.print(
                f"\n[yellow]{len(unattributable)}[/yellow] charter(s) are held by "
                "a generalist, so nothing they produce can be attributed to any "
                "one of them."
            )
            console.print(
                "[dim]That is not the same as being idle, and the difference is "
                "the reason to split a role rather than to hire for one.[/dim]"
            )
    finally:
        runtime.close()


@orgdev_app.command("scan")
def org_scan(workspace: WorkspaceOption = None) -> None:
    """Which declared triggers currently fire, and on what reading."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            hits = scan(session)
        table = Table(title="declared triggers")
        for column in ("trigger", "rule", "asks"):
            table.add_column(column)
        for trigger in TRIGGERS:
            table.add_row(trigger.kind.value, trigger.describe(), trigger.asks)
        console.print(table)

        if not hits:
            console.print("\n[green]nothing fires[/green]")
            return
        fired = Table(title="firing now")
        for column in ("agent", "trigger", "value", "threshold", "proposes"):
            fired.add_column(column)
        for hit in hits:
            fired.add_row(
                f"{hit.handle} ({hit.subject})",
                hit.trigger.metric,
                str(hit.reading.value),
                str(hit.trigger.threshold),
                hit.trigger.proposes.value,
            )
        console.print(fired)
        console.print(
            "[dim]A reading that could not be taken never fires a trigger. "
            "Reorganising because the instrumentation has a hole would be "
            "acting on the absence of a measurement.[/dim]"
        )
    finally:
        runtime.close()


@orgdev_app.command("changes")
def org_changes(workspace: WorkspaceOption = None) -> None:
    """Every change the company has proposed to itself, and what it did."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = runtime.orgdev.history(session)
            transfers = session.execute(
                sa.select(sa.func.count()).select_from(CoverageTransfer)
            ).scalar_one()
        if not rows:
            console.print("[yellow]the company has not changed its own shape[/yellow]")
            return
        table = Table(title="org changes")
        for column in ("ref", "kind", "state", "about", "predicted", "effect"):
            table.add_column(column)
        for row in rows:
            tone = _TONE.get(row.effect or "", "dim")
            table.add_row(
                row.ref,
                row.kind,
                row.state,
                row.subject_agent,
                f"{row.predicted_metric} {row.predicted_direction} "
                f"{row.predicted_magnitude}",
                f"[{tone}]{row.effect or '—'}[/{tone}]",
            )
        console.print(table)
        for row in rows:
            if row.effect_detail:
                console.print(f"[dim]{row.ref}: {escape(row.effect_detail)}[/dim]")
        console.print(
            f"\n[dim]{transfers} charter transfer(s) recorded. Coverage moves; "
            "it is never dropped and recreated, so the holder of any charter at "
            "any past moment is reconstructable.[/dim]"
        )
    finally:
        runtime.close()


@orgdev_app.command("show")
def org_show(
    change_ref: Annotated[str, typer.Argument(help="Change, e.g. ORG-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """One change: the trigger, the locked prediction, and the verdict."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            row = session.execute(
                sa.select(OrgChange).where(OrgChange.ref == change_ref)
            ).scalar_one_or_none()
            if row is None:
                console.print(f"[red]no change {escape(change_ref)}[/red]")
                raise typer.Exit(2)
            moved = list(
                session.execute(
                    sa.select(CoverageTransfer)
                    .where(CoverageTransfer.change_ref == change_ref)
                    .order_by(CoverageTransfer.charter_id)
                ).scalars()
            )
        console.print(f"[bold]{escape(row.ref)}[/bold]  {row.kind}  {row.state}")
        console.print(f"  about      {escape(row.subject_agent)}")
        console.print(f"  proposed   {escape(row.proposed_by)}")
        console.print(f"  trigger    {escape(row.trigger)}")
        for key, value in sorted(row.trigger_evidence.items()):
            console.print(f"      {escape(key)}: {escape(str(value))}")
        console.print(f"  justifies  {escape(row.justification[:200])}")
        console.print(
            f"\n  [bold]predicted[/bold]  {escape(row.predicted_metric)} "
            f"{escape(row.predicted_direction)} by at least "
            f"{escape(row.predicted_magnitude)}"
        )
        console.print(f"  plan       {escape(row.measurement_plan)}")
        console.print(
            f"  locked     {escape((row.locked_digest or '')[:16])} at {row.locked_at}"
        )
        console.print(f"  decided in {escape(row.meeting_ref or '—')}")
        if moved:
            console.print(f"\n  [bold]moved[/bold] ({len(moved)})")
            for transfer in moved:
                console.print(
                    f"      {escape(transfer.charter_id)}: "
                    f"{escape(transfer.from_agent)} -> {escape(transfer.to_agent)}"
                )
        tone = _TONE.get(row.effect or "", "dim")
        console.print(
            f"\n  [bold]measured[/bold]  baseline {row.baseline} -> "
            f"{row.realised}  [{tone}]{row.effect or 'not yet'}[/{tone}]"
        )
        if row.effect_detail:
            console.print(f"  {escape(row.effect_detail)}")
        if row.effect and row.effect != EffectVerdict.IMPROVED.value:
            console.print(
                "[dim]Recorded as it came out. The prediction was hashed "
                "before the Board saw it, so there was no way to re-aim it "
                "once the number was known.[/dim]"
            )
    finally:
        runtime.close()


@orgdev_app.command("experiment")
def org_experiment(
    workspace: WorkspaceOption = None,
    record: Annotated[bool, typer.Option(help="Write the results down.")] = False,
) -> None:
    """Run the standing questions the company asks about its own shape."""
    runtime = _runtime(workspace)
    try:
        table = Table(title="org experiments")
        for column in ("question", "arm", "caught", "false alarms", "verdict"):
            table.add_column(column)
        for question, control, treatment in STANDING_QUESTIONS:
            before, after = runtime.org_experiments.compare(control, treatment)
            from aurelis.orgdev.experiments import _verdict

            verdict, detail = _verdict(before.score, after.score)
            tone = {
                "treatment_better": "green",
                "control_better": "yellow",
                "no_difference": "dim",
            }.get(verdict, "yellow")
            table.add_row(
                question,
                control.name,
                f"{before.score.caught}/{before.score.planted}",
                str(before.score.false_alarms),
                "",
            )
            table.add_row(
                "",
                treatment.name,
                f"{after.score.caught}/{after.score.planted}",
                str(after.score.false_alarms),
                f"[{tone}]{verdict}[/{tone}]",
            )
            if record:
                with runtime.database.session() as session:
                    runtime.org_experiments.run(
                        session,
                        question=question,
                        control=control,
                        treatment=treatment,
                    )
        console.print(table)
        console.print(
            "\n[dim]More agents help only when they widen what the room is "
            "asked. A second seat with a specialty the room already has moves "
            "nothing at all — the union of a set with a subset of itself is "
            "the set.[/dim]"
        )
        console.print(
            "[dim]Measured on planted defects, not on a market; and the panels "
            "differ in procedure, not in reasoning ability.[/dim]"
        )
    finally:
        runtime.close()


@orgdev_app.command("experiments")
def org_experiments_recorded(workspace: WorkspaceOption = None) -> None:
    """Org experiments the company has already run and written down."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = list(
                session.execute(
                    sa.select(OrgExperiment).order_by(OrgExperiment.ran_at)
                ).scalars()
            )
        if not rows:
            console.print("[yellow]no org experiment has been recorded[/yellow]")
            return
        table = Table(title="recorded org experiments")
        for column in ("ref", "question", "verdict", "detail"):
            table.add_column(column)
        for row in rows:
            table.add_row(row.ref, row.question, row.verdict, row.detail)
        console.print(table)
    finally:
        runtime.close()


@orgdev_app.command("develop")
def org_develop(workspace: WorkspaceOption = None) -> None:
    """The demonstration: two structural changes, proposed to measured."""
    from aurelis.orgdev.demonstration import run_org_development

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        runtime.staff()
        outcome = run_org_development(runtime)
    finally:
        runtime.close()

    for step in outcome.steps:
        tone = _TONE.get(step.effect.verdict.value, "dim")
        console.print(
            f"\n[bold]{escape(step.change_ref)}[/bold]  "
            f"{escape(step.subject)} {step.breadth_before} -> "
            f"{step.breadth_after} charters"
        )
        console.print(
            f"  trigger    {step.trigger.value} = {escape(step.trigger_value)}"
        )
        console.print(
            f"  predicted  {escape(step.predicted)}  "
            f"[dim](locked {escape(step.locked_digest[:12])} before "
            f"{escape(step.meeting_ref)})[/dim]"
        )
        console.print(f"  handover   {escape(step.handover)}")
        console.print(
            f"  new agent  {escape(step.new_agent)}  "
            f"training: {escape(step.new_agent_verdict)}"
        )
        console.print(
            f"  [bold][{tone}]{step.effect.verdict.value.upper()}[/{tone}][/bold]  "
            f"{escape(step.effect.detail)}"
        )

    console.print(
        f"\ncoverage intact after both: "
        f"[{'green' if outcome.coverage_intact else 'red'}]"
        f"{outcome.coverage_intact}[/]"
    )
    console.print(
        "[dim]Every charter in the registry is held by exactly one working "
        "agent. Coverage moved by a single UPDATE at every step, so no charter "
        "was ever held by nobody.[/dim]"
    )
    if outcome.discriminates:
        console.print(
            "\n[dim]The first change was sensible, clean, and did not do what "
            "it was sold on. It is recorded as a failure because the "
            "prediction was hashed before the Board saw it.[/dim]"
        )


__all__ = ["orgdev_app"]
