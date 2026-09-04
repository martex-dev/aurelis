"""``aurelis research`` — running a hypothesis to a verdict, and reading the record.

The demonstration is deliberately not rigged. It registers a momentum claim,
runs it, and reports whatever the verdict rule returns — which on fixture data
is usually not a discovery. That is the point: a research system that only ever
shows you confirmations is not a research system.
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

from aurelis.engines import DataSpec, ExperimentSpec, SignalSpec, UniverseSpec, survey
from aurelis.research.states import HypothesisState, RegistrationKind, Verdict
from aurelis.research.tables import Hypothesis, Registration, Result, Run
from aurelis.runtime import Runtime

console = Console()

research_app = typer.Typer(
    help="Hypotheses, preregistration, runs and verdicts.", no_args_is_help=True
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_VERDICT_COLOUR = {
    Verdict.CONFIRMED: "green",
    Verdict.REFUTED: "red",
    Verdict.INCONCLUSIVE: "yellow",
    Verdict.UNDERPOWERED: "yellow",
    Verdict.INVALID: "red",
}


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@research_app.command("run")
def research_run(
    workspace: WorkspaceOption = None,
    signal: Annotated[
        str, typer.Option(help="momentum, mean_reversion, always_long.")
    ] = "momentum",
    lookback: Annotated[int, typer.Option(help="Signal lookback in bars.")] = 12,
    bars: Annotated[int, typer.Option(help="How many bars to test over.")] = 240,
    minimum_effect: Annotated[
        str, typer.Option(help="Smallest Sharpe worth caring about.")
    ] = "0.05",
    cells: Annotated[int, typer.Option(help="Cells this family declares.")] = 8,
) -> None:
    """Take one hypothesis from a claim to a verdict.

    Propose, screen for prior art, lock a preregistration, design, run, and
    derive the verdict from criteria fixed before anything executed. Nothing
    here can decide what counts as success after seeing the numbers.
    """
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        runtime.staff()

        spec = ExperimentSpec(
            engine="local",
            universe=UniverseSpec(desk="crypto", symbols=("BTC/USDT",)),
            data=DataSpec(source="fixture", bars=bars),
            signal=SignalSpec(kind=signal, lookback=lookback),
            metrics=("total_return", "sharpe", "max_drawdown", "n_trades", "cost_drag"),
        )

        with runtime.database.session() as session:
            quant = runtime.roster.by_handle(session, "QUANT").ref
            registrar = runtime.roster.by_handle(session, "GOV").ref

            hypothesis = runtime.research.propose(
                session,
                claim=(
                    f"{signal} over {lookback} bars earns a Sharpe above zero "
                    "after costs."
                ),
                author=quant,
                minimum_effect=Decimal(minimum_effect),
                primary_metric="sharpe",
                family=f"strategy.{signal}.crypto",
                desk="crypto",
                rationale="Fixture data; this is a lifecycle demonstration.",
            )
            runtime.research.screen(session, hypothesis.ref)
            registration = runtime.research.register(
                session,
                hypothesis_ref=hypothesis.ref,
                spec=spec,
                registrar=registrar,
                declared_cells=cells,
                analysis_plan=(
                    "Per-bar Sharpe with a normal-approximation interval; the "
                    "lower bound must exceed zero."
                ),
                pass_criteria=[
                    {"metric": "sharpe", "comparison": "gt", "value": "0", "on": "low"}
                ],
                kind=RegistrationKind.CONFIRMATORY,
            )
            experiment = runtime.research.design(
                session, registration_ref=registration.ref, designer=quant
            )
            run, artifact = runtime.research.execute(
                session, experiment_ref=experiment.ref
            )
            outcome = runtime.research.conclude(
                session,
                run_ref=run.ref,
                artifact=artifact,
                author=quant,
                interpretation=(
                    "Recorded by the lifecycle demonstration; the verdict was "
                    "derived by rule, not written here."
                ),
            )
            trials = runtime.research.trial_count(session, f"strategy.{signal}")
            verification = runtime.ledger.verify(session)
            locked = registration.locked_at
    finally:
        runtime.close()

    colour = _VERDICT_COLOUR[outcome.verdict]
    console.print(
        f"\n[bold]{outcome.hypothesis_ref}[/bold]  "
        f"[{colour}]{outcome.verdict.value.upper()}[/{colour}]\n"
        f"{escape(outcome.report.reason)}\n"
    )

    table = Table(show_header=False, box=None)
    table.add_column("", style="bold", width=16)
    table.add_column("")
    table.add_row("registration", f"{outcome.registration_ref}  locked {locked}")
    table.add_row("spec digest", registration.spec_digest[:16])
    table.add_row("run", f"{outcome.run_ref}  data {artifact.data_fingerprint[:12]}")
    table.add_row("declared cells", f"{trials} in this family")
    for name, value in outcome.metrics.items():
        table.add_row(name, value)
    table.add_row(
        "chain",
        f"[green]{verification.describe()}[/green]"
        if verification.ok
        else f"[red]{verification.describe()}[/red]",
    )
    console.print(table)

    console.print("\n[bold]HOW THE VERDICT WAS DERIVED[/bold]")
    for check in outcome.report.checks:
        console.print(f"  {escape(check)}")

    console.print(
        "\n[dim]Criteria were locked before the run existed. The verdict is a "
        "pure function of those criteria and the measured interval.[/dim]"
    )
    if not verification.ok:
        raise typer.Exit(code=1)


@research_app.command("graveyard")
def research_graveyard(workspace: WorkspaceOption = None) -> None:
    """Everything the company killed, and why.

    A first-class view, not a hidden tab. Failed research is the corpus that
    raises the bar for every future claim.
    """
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            dead = runtime.research.graveyard(session)
            total = session.execute(
                sa.select(sa.func.count()).select_from(Hypothesis)
            ).scalar_one()
    finally:
        runtime.close()

    if not dead:
        console.print("[dim]Nothing killed yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("ref", width=10)
    table.add_column("verdict", width=14)
    table.add_column("family", width=28)
    table.add_column("why", overflow="fold")
    for hypothesis in dead:
        state = HypothesisState(hypothesis.state)
        colour = "red" if state is HypothesisState.REFUTED else "yellow"
        table.add_row(
            hypothesis.ref,
            f"[{colour}]{hypothesis.state}[/{colour}]",
            hypothesis.family,
            hypothesis.verdict_reason or "[dim]shelved before running[/dim]",
        )
    console.print(table)
    console.print(
        f"\n[dim]{len(dead)} of {total} hypotheses did not survive. "
        "Every one raises the bar for the next claim.[/dim]"
    )


@research_app.command("show")
def research_show(
    ref: Annotated[str, typer.Argument(help="Hypothesis reference, e.g. HYP-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """One hypothesis: its registration, its run, and every number's source."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            try:
                hypothesis = runtime.research.hypothesis(session, ref.upper())
            except KeyError:
                console.print(f"[red]No hypothesis {escape(ref)!r}.[/red]")
                raise typer.Exit(code=1) from None

            registrations = session.execute(
                sa.select(Registration).where(Registration.hypothesis_ref == hypothesis.ref)
            ).scalars().all()
            runs = session.execute(
                sa.select(Run).where(
                    Run.registration_ref.in_([r.ref for r in registrations] or [""])
                )
            ).scalars().all()
            results = {
                run.ref: session.execute(
                    sa.select(Result).where(Result.run_ref == run.ref)
                ).scalars().all()
                for run in runs
            }
    finally:
        runtime.close()

    console.print(
        f"\n[bold]{hypothesis.ref}[/bold]  [dim]{hypothesis.state} · "
        f"{hypothesis.family}[/dim]\n{escape(hypothesis.claim)}\n"
    )
    console.print(
        f"  minimum effect  {hypothesis.minimum_effect} on {hypothesis.primary_metric}"
    )
    if hypothesis.verdict_reason:
        console.print(f"  verdict         {escape(hypothesis.verdict_reason)}")
    if hypothesis.prior_art:
        console.print(f"  prior art       {', '.join(hypothesis.prior_art)}")
    console.print()

    for registration in registrations:
        console.print(
            f"[bold]{registration.ref}[/bold]  {registration.kind}, "
            f"{registration.declared_cells} declared cell(s), "
            f"locked {registration.locked_at}"
        )
        console.print(f"  spec   {registration.spec_digest[:16]}")
        console.print(f"  plan   {escape(registration.analysis_plan)}")
        for criterion in registration.pass_criteria:
            console.print(
                f"  bar    {criterion['metric']}.{criterion.get('on', 'low')} "
                f"{criterion['comparison']} {criterion['value']}"
            )
        if registration.degraded_reason:
            console.print(f"  [yellow]{escape(registration.degraded_reason)}[/yellow]")
        console.print()

    for run in runs:
        console.print(
            f"[bold]{run.ref}[/bold]  {run.status}, {run.engine}, "
            f"code {run.code_version}, data {run.data_fingerprint[:12]}"
        )
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("metric", width=16)
        table.add_column("value", width=14)
        table.add_column("interval", width=26)
        table.add_column("computed by", width=12)
        table.add_column("method", overflow="fold")
        for result in results.get(run.ref, []):
            interval = (
                f"[{result.low}, {result.high}]"
                if result.low is not None
                else "[dim]none[/dim]"
            )
            table.add_row(
                result.metric,
                str(result.value),
                interval,
                result.computed_by,
                result.method,
            )
        console.print(table)
        console.print()


@research_app.command("engines")
def research_engines() -> None:
    """Which engines exist, and what each can actually do."""
    for capabilities in survey():
        colour = "green" if capabilities.available else "yellow"
        console.print(
            f"[bold]{capabilities.name}[/bold]  "
            f"[{colour}]{'available' if capabilities.available else 'unavailable'}[/{colour}]"
        )
        console.print(f"  {escape(capabilities.detail)}")
        if capabilities.available:
            console.print(f"  signals  {', '.join(sorted(capabilities.signals))}")
            console.print(f"  metrics  {', '.join(sorted(capabilities.metrics))}")
            console.print(f"  desks    {', '.join(sorted(capabilities.desks))}")
        console.print()

@research_app.command("review")
def research_review(
    workspace: WorkspaceOption = None,
    bars: Annotated[int, typer.Option(help="Window length in bars.")] = 200,
) -> None:
    """The M5 demonstration: a confirmed claim, challenged and killed.

    A researcher registers a drawdown claim over the universe of instruments
    still trading, runs it, and it is CONFIRMED. A Critic names SURVIVORSHIP.
    The Chair dispatches the generated test -- the same rule over the universe
    as it actually stood, delisted names restored. The measurement comes back,
    the objection is upheld, and the hypothesis is refuted.

    Nobody intervenes at any point.
    """
    from aurelis.research.review import hold_research_review

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        runtime.staff()
        with runtime.database.session() as session:
            quant = runtime.roster.by_handle(session, "QUANT").ref
            critic = runtime.roster.by_handle(session, "CRITIC").ref
            lead = runtime.roster.by_handle(session, "LEAD-R").ref
            outcome = hold_research_review(
                session,
                research=runtime.research,
                chair=runtime.chair,
                author=quant,
                critic=critic,
                chair_ref=runtime.roster.by_handle(session, "OPS").ref,
                participants=(quant, critic, lead),
                registrar=runtime.roster.by_handle(session, "GOV").ref,
                bars=bars,
            )
            verification = runtime.ledger.verify(session)
    finally:
        runtime.close()

    console.print()
    console.print(
        f"[bold]{outcome.hypothesis_ref}[/bold]  "
        f"[green]{outcome.verdict_before.value.upper()}[/green] -> "
        f"[red]{outcome.verdict_after.value.upper()}[/red]"
    )
    console.print()

    table = Table(show_header=False, box=None)
    table.add_column("", style="bold", width=18)
    table.add_column("")
    table.add_row("claimed", f"{outcome.metric} < 0.20, measured {outcome.claimed}")
    table.add_row("universe", f"{outcome.universe_before} names (still trading)")
    table.add_row("objection", f"{outcome.objection_ref} SURVIVORSHIP, critical")
    table.add_row("test", "the same rule, universe restored to point-in-time")
    table.add_row("re-run universe", f"{outcome.universe_after} names")
    table.add_row("restored", ", ".join(outcome.excluded))
    table.add_row(
        outcome.metric,
        f"[green]{outcome.claimed}[/green] -> [red]{outcome.measured}[/red]",
    )
    table.add_row("verdict", f"[red]{outcome.objection_status.value.upper()}[/red]")
    table.add_row(
        "chain",
        f"[green]{verification.describe()}[/green]"
        if verification.ok
        else f"[red]{verification.describe()}[/red]",
    )
    console.print(table)

    console.print()
    console.print(f"  [dim]{escape(outcome.detail)}[/dim]")
    console.print()
    console.print(
        "[dim]The universe was chosen knowing which names survived. A top-1 "
        "rotation is drawn to whatever runs hottest, and the names that later "
        "delisted ran hottest of all right before they stopped.[/dim]"
    )
    console.print(
        "[dim]martex-quant found this same defect on real crypto history, where "
        "it took a Sharpe of 1.47 to 0.86. Those figures belong to that corpus; "
        "the ones above are what this engine measured.[/dim]"
    )
    console.print()

    if not outcome.overturned:
        console.print("[yellow]The review did not overturn the claim.[/yellow]")
        raise typer.Exit(code=1)
    console.print(
        "[green]M5 acceptance: a confirmed result refuted by a measurement, "
        "with no human in the loop.[/green]"
    )


@research_app.command("defects")
def research_defects() -> None:
    """The market defects a Critic can allege, and how each is settled."""
    from aurelis.meetings.taxonomy import MARKET_DEFECTS

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("defect", style="bold", width=20)
    table.add_column("severity", width=10)
    table.add_column("varies", width=30)
    table.add_column("asks", overflow="fold")
    for defect in MARKET_DEFECTS.values():
        colour = "red" if defect.severity.value == "critical" else "yellow"
        table.add_row(
            defect.name,
            f"[{colour}]{defect.severity.value}[/{colour}]",
            defect.varies,
            defect.asks,
        )
    console.print(table)
    console.print()
    console.print(
        "[dim]A Critic names a defect; the test is generated from the "
        "specification under review. The prose is the critic's; the arithmetic "
        "is not.[/dim]"
    )
