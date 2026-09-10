"""``aurelis trading`` — the paper book, the chain behind it, and the gap.

``chain`` is the command worth having: given an order, it walks backwards to
the approval, the assessment and the proposal that produced it, and prints the
three numbers. If any link were missing the order could not exist, so the
output is a demonstration rather than a report.
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

from aurelis.core.errors import IntegrityViolation
from aurelis.risk.tables import RiskAssessment, TradeApproval, TradeProposal
from aurelis.runtime import Runtime
from aurelis.strategy.tables import StrategyVersion
from aurelis.trading.posttrade import DIRECTIONS, Direction
from aurelis.trading.readiness import Readiness
from aurelis.trading.tables import Fill, GapMeasurement, Order, Position

console = Console()

trading_app = typer.Typer(
    help="Paper trading: the approval chain, positions, and the backtest gap.",
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


@trading_app.command("brokers")
def trading_brokers(workspace: WorkspaceOption = None) -> None:
    """Which brokers exist. There are three, and none of them is live."""
    runtime = _runtime(workspace)
    try:
        table = Table(title="broker adapters")
        for column in ("kind", "what it knows"):
            table.add_column(column)
        table.add_row(
            "backtest", "fills at the expected price plus the declared cost model"
        )
        table.add_row("simulation", "replays a scripted sequence of outcomes")
        table.add_row("paper", "fills against an observed price — reality gets a vote")
        console.print(table)
        console.print(
            "[dim]There is no live adapter. Not disabled — absent: no "
            "BrokerKind member, no registry entry, and no code path that could "
            "reach one (ADR-0006).[/dim]"
        )
    finally:
        runtime.close()


@trading_app.command("positions")
def trading_positions(
    portfolio_ref: Annotated[str, typer.Argument(help="Portfolio, e.g. PTF-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """What the book holds, and what it cost."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = list(
                session.execute(
                    sa.select(Position)
                    .where(Position.portfolio_ref == portfolio_ref)
                    .order_by(Position.symbol)
                ).scalars()
            )
        if not rows:
            console.print("[yellow]the book holds nothing[/yellow]")
            return
        table = Table(title=f"positions in {portfolio_ref}")
        for column in ("symbol", "quantity", "average", "realised P&L", "fees"):
            table.add_column(column)
        for row in rows:
            table.add_row(
                row.symbol,
                str(row.quantity),
                str(row.average_price),
                str(row.realised_pnl),
                str(row.fees_paid),
            )
        console.print(table)
    finally:
        runtime.close()


@trading_app.command("chain")
def trading_chain(
    order_ref: Annotated[str, typer.Argument(help="Order reference, e.g. ORD-0001.")],
    workspace: WorkspaceOption = None,
) -> None:
    """Walk one order back to the decision that permitted it."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            order = session.execute(
                sa.select(Order).where(Order.ref == order_ref)
            ).scalar_one_or_none()
            if order is None:
                console.print(f"[red]no order {escape(order_ref)}[/red]")
                raise typer.Exit(2)
            approval = session.execute(
                sa.select(TradeApproval).where(TradeApproval.ref == order.approval_ref)
            ).scalar_one()
            assessment = session.execute(
                sa.select(RiskAssessment).where(
                    RiskAssessment.ref == approval.assessment_ref
                )
            ).scalar_one()
            proposal = session.execute(
                sa.select(TradeProposal).where(
                    TradeProposal.ref == approval.proposal_ref
                )
            ).scalar_one()
            fills = list(
                session.execute(
                    sa.select(Fill).where(Fill.order_ref == order_ref)
                ).scalars()
            )

        console.print(f"[bold]{escape(order.ref)}[/bold]  {escape(order.status)}")
        console.print(
            f"  {escape(proposal.ref)}  proposed by {escape(proposal.proposed_by)}: "
            f"{escape(proposal.rationale[:70])}"
        )
        console.print(
            f"  {escape(assessment.ref)}  [bold]{escape(assessment.decision.upper())}[/bold] "
            f"by {escape(assessment.assessor)}"
        )
        console.print(f"      {escape(assessment.reason[:100])}")
        console.print(
            f"  {escape(approval.ref)}  approved by {escape(approval.approved_by)}"
        )
        console.print(
            f"  {escape(order.ref)}  {escape(order.side)} {order.quantity} "
            f"{escape(order.symbol)} on the {escape(order.broker)} broker"
        )
        for fill in fills:
            console.print(
                f"      filled {fill.quantity} at {fill.price} (fee {fill.fee})"
            )

        console.print("\n[bold]The three numbers[/bold]")
        console.print(f"  desired  {proposal.desired_exposure}")
        console.print(f"  allowed  {proposal.allowed_exposure}")
        console.print(f"  final    {proposal.final_target}")
        console.print(
            "\n[dim]Every link is a foreign key with a trigger behind it. An "
            "order without this chain cannot exist.[/dim]"
        )
    finally:
        runtime.close()


@trading_app.command("gap")
def trading_gap(
    workspace: WorkspaceOption = None,
    metric: Annotated[str, typer.Option(help="Which metric to summarise.")] = "",
) -> None:
    """Backtest expectation against what paper actually produced."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = list(
                session.execute(
                    sa.select(GapMeasurement).order_by(GapMeasurement.period_end)
                ).scalars()
            )
            metrics = sorted({row.metric for row in rows})
            means = {
                name: runtime.posttrade.company_gap(session, name) for name in metrics
            }

        if not rows:
            console.print(
                "[yellow]no gap measured yet — nothing has been paper traded "
                "through a full period[/yellow]"
            )
            return

        table = Table(title="backtest vs paper")
        for column in ("version", "metric", "expected", "realised", "gap", "held"):
            table.add_column(column)
        for row in rows:
            if metric and row.metric != metric:
                continue
            # Through the one implementation, so this cannot drift from what
            # the Gap object says. Reading `row.gap >= 0` here printed
            # "held: yes" beside a measurement that had fallen short.
            gap = runtime.posttrade.as_gap(row)
            neutral = gap.direction is Direction.NEUTRAL
            held = not neutral and gap.held
            table.add_row(
                row.version_ref,
                row.metric,
                str(row.expected),
                str(row.realised),
                f"[{'dim' if neutral else 'green' if held else 'red'}]{row.gap:+}[/]",
                "—" if neutral else ("yes" if held else "no"),
            )
        console.print(table)

        console.print("\n[bold]Company competence[/bold]")
        for name, mean in means.items():
            if mean is None:
                continue
            direction = DIRECTIONS.get(name, Direction.NEUTRAL)
            if direction is Direction.HIGHER_IS_BETTER:
                good: bool | None = mean >= 0
            elif direction is Direction.LOWER_IS_BETTER:
                good = mean <= 0
            else:
                good = None
            tone = "dim" if good is None else ("green" if good else "red")
            console.print(
                f"  mean {name} gap  [{tone}]{mean:+}[/]  "
                f"[dim]({direction.value})[/dim]"
            )
        console.print(
            "[dim]How wrong our backtests tend to be is a fact about us, not "
            "about any one strategy.[/dim]"
        )
    finally:
        runtime.close()


@trading_app.command("alerts")
def trading_alerts(workspace: WorkspaceOption = None) -> None:
    """Open alerts, and whether anyone has looked at them."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = runtime.alerts.open(session)
        if not rows:
            console.print("[green]no open alerts[/green]")
            return
        table = Table(title="open alerts")
        for column in ("ref", "severity", "source", "about", "looked at", "message"):
            table.add_column(column)
        for row in rows:
            tone = {"critical": "red", "warning": "yellow"}.get(row.severity, "dim")
            table.add_row(
                row.ref,
                f"[{tone}]{row.severity}[/{tone}]",
                row.source,
                row.subject or "—",
                row.acknowledged_by or "[red]nobody[/red]",
                row.message[:60],
            )
        console.print(table)
        for row in rows:
            console.print(f"[dim]{row.ref}: {escape(row.recommended_action)}[/dim]")
    finally:
        runtime.close()


# ------------------------------------------------------------ the driver


def _latest_authored(session: sa.orm.Session) -> str | None:
    from aurelis.authoring.tables import AuthoringAttempt

    return session.execute(
        sa.select(AuthoringAttempt.version_ref)
        .where(AuthoringAttempt.refused_at.is_(None))
        .order_by(AuthoringAttempt.created_at.desc())
    ).scalars().first()


def _actors(runtime: Runtime, session: sa.orm.Session) -> dict[str, str]:
    """Who does what in the chain. Six seats, and deliberately not one agent.

    The agent that wants the exposure must not be the agent that approves it,
    and neither may be the one that validated the evidence. Read from the
    roster rather than named here, so a company that reorganised its seats
    changes this by changing the roster.
    """
    handle = {
        "validator": "VALID",
        "governor": "GOV",
        "risk": "RISK",
        "portfolio": "PM",
        "trader": "TRADE",
    }
    return {role: runtime.roster.by_handle(session, name).ref for role, name in handle.items()}


def _cycle_actors(refs: dict[str, str]) -> dict[str, str]:
    return {
        "proposer": refs["portfolio"],
        "assessor": refs["risk"],
        "approver": refs["trader"],
        "executor": refs["trader"],
        "analyst": refs["trader"],
    }


def _readiness_table(readiness: Readiness, desk: str) -> Table:
    from aurelis.strategy.gates import COMPARISONS, default_criteria

    criteria = default_criteria(desk)
    table = Table(title=f"what the record says about {readiness.version_ref}")
    for column in ("gate", "metric", "criterion", "observed", "verdict", "from"):
        table.add_column(column, overflow="fold")
    for item in readiness.evidence:
        criterion = criteria[item.gate]
        bar = f"{criterion['comparison']} {criterion['value']}"
        if item.value is None:
            verdict = "[yellow]SILENT[/yellow]"
            observed = "—"
        else:
            passed = COMPARISONS[str(criterion["comparison"])](
                item.value, Decimal(str(criterion["value"]))
            )
            verdict = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
            observed = str(item.value)
        table.add_row(
            item.gate.value, item.metric, bar, observed, verdict, escape(item.source)
        )
    return table


@trading_app.command("readiness")
def trading_readiness(
    version_ref: Annotated[
        str, typer.Argument(help="Version, e.g. SV-0001. Defaults to the latest authored.")
    ] = "",
    workspace: WorkspaceOption = None,
    weight: Annotated[
        str, typer.Option(help="Share of the book the deployment would take.")
    ] = "0.25",
    equity: Annotated[str, typer.Option(help="Paper book equity, if none is open.")] = "100000",
) -> None:
    """What stands between an authored version and a paper book.

    Reads seven gates out of the company's own record and reports each one as
    a number, a failure, or a silence. A silence is not a zero: it says the
    record holds nothing on the question, and a gate nobody can answer cannot
    be passed.
    """
    from aurelis.trading.readiness import gather, intended_notional

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            target = version_ref or _latest_authored(session)
            if target is None:
                console.print(
                    "[yellow]no version has been authored yet — run "
                    "`aurelis strategy author` first[/yellow]"
                )
                raise typer.Exit(2)
            version = session.execute(
                sa.select(StrategyVersion).where(StrategyVersion.ref == target)
            ).scalar_one_or_none()
            if version is None:
                console.print(f"[red]no version {escape(target)}[/red]")
                raise typer.Exit(2)
            book = _paper_book(session)
            intended = (
                intended_notional(
                    session, portfolio_ref=book, weight=Decimal(weight)
                )
                if book
                else (Decimal(equity) * Decimal(weight)).quantize(Decimal("0.01"))
            )
            try:
                readiness = gather(
                    session,
                    version_ref=target,
                    portfolio_ref=book or None,
                    intended=intended,
                )
            except IntegrityViolation as refusal:
                console.print(f"[yellow]{escape(str(refusal))}[/yellow]")
                raise typer.Exit(2) from None
            desk = version.desk
    finally:
        runtime.close()

    console.print(_readiness_table(readiness, desk))
    if readiness.silent:
        console.print(
            f"\n[yellow]{len(readiness.silent)} gate(s) cannot be evaluated.[/yellow] "
            "A promotion needs every gate evaluated, so this version cannot "
            "reach a paper book until the record can answer them."
        )
    else:
        console.print(
            "\n[dim]Every gate has an observable. Whether they pass is a "
            "separate question, answered above.[/dim]"
        )


def _paper_book(session: sa.orm.Session) -> str:
    from aurelis.portfolio.tables import Portfolio

    ref = session.execute(
        sa.select(Portfolio.ref)
        .where(Portfolio.mode == "paper")
        .order_by(Portfolio.created_at)
    ).scalars().first()
    return str(ref) if ref else ""


@trading_app.command("deploy")
def trading_deploy(
    version_ref: Annotated[
        str, typer.Argument(help="Version to deploy. Defaults to the latest authored.")
    ] = "",
    workspace: WorkspaceOption = None,
    weight: Annotated[str, typer.Option(help="Share of the book to allocate.")] = "0.25",
    equity: Annotated[str, typer.Option(help="Paper book equity, if none is open.")] = "100000",
) -> None:
    """Take an authored version as far towards a paper book as it can go.

    Registers each gate's criterion, evaluates the ones the record can answer,
    and asks for promotion. A refusal is the ordinary outcome and is printed
    with the evidence that produced it.
    """
    from aurelis.trading.deployment import deploy, open_paper_book

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            target = version_ref or _latest_authored(session)
            if target is None:
                console.print("[yellow]nothing has been authored yet[/yellow]")
                raise typer.Exit(2)
            version = session.execute(
                sa.select(StrategyVersion).where(StrategyVersion.ref == target)
            ).scalar_one_or_none()
            if version is None:
                console.print(f"[red]no version {escape(target)}[/red]")
                raise typer.Exit(2)
            refs = _actors(runtime, session)
            book = open_paper_book(
                runtime,
                session,
                desk=version.desk,
                equity=Decimal(equity),
                opened_by=refs["portfolio"],
            )
            try:
                outcome = deploy(
                    runtime,
                    session,
                    version_ref=target,
                    portfolio_ref=book,
                    weight=Decimal(weight),
                    actors=refs,
                )
            except IntegrityViolation as refusal:
                console.print(f"[yellow]not deployed[/yellow] — {escape(str(refusal))}")
                raise typer.Exit(2) from None
            desk = version.desk
    finally:
        runtime.close()

    console.print()
    console.print(_readiness_table(outcome.readiness, desk))
    console.print()
    if outcome.already:
        console.print(f"[dim]{escape(outcome.describe())}[/dim]")
        return
    if outcome.deployed:
        console.print(f"[green]{escape(outcome.describe())}[/green]")
        console.print(
            "[dim]Risk holds an exposure limit at the sleeve. Every intent the "
            "walk produces goes through it.[/dim]"
        )
        return
    console.print(f"[yellow]not deployed[/yellow] — {escape(outcome.refusal)}")
    for failure in outcome.failures:
        console.print(f"  [red]fail[/red] {escape(failure)}")
    console.print(
        "\n[dim]A refusal here is the promotion machinery working, and it "
        "wrote nothing: no gate registered, no state moved, no allocation "
        "made. Every number above came from the record rather than from this "
        "command.[/dim]"
    )


@trading_app.command("paper")
def trading_paper(
    workspace: WorkspaceOption = None,
    bars: Annotated[int, typer.Option(help="Cap the walk. 0 walks the whole hold-out.")] = 0,
) -> None:
    """Walk the snapshot's held-out tail, then measure against the backtest.

    Every bar is one turn of the paper cycle: what the rule wants, what Risk
    permits, what the broker filled. The equity curve is then derived back out
    of the fills, and compared against the numbers the run that justified the
    deployment actually produced.
    """
    from aurelis.intel.snapshots import MarketSnapshot, latest_snapshot
    from aurelis.trading.paper import measure, walk

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            book = _paper_book(session)
            if not book:
                console.print(
                    "[yellow]no paper book is open — run `aurelis trading "
                    "deploy` first[/yellow]"
                )
                raise typer.Exit(2)
            snapshot: MarketSnapshot | None = latest_snapshot(session)
            if snapshot is None:
                console.print(
                    "[yellow]no market snapshot has been recorded — run "
                    "`aurelis data fetch` first[/yellow]"
                )
                raise typer.Exit(2)
            refs = _actors(runtime, session)
            try:
                walked = walk(
                    runtime,
                    session,
                    portfolio_ref=book,
                    snapshot=snapshot,
                    actors=_cycle_actors(refs),
                    limit=bars,
                )
                gaps = measure(
                    runtime,
                    session,
                    portfolio_ref=book,
                    snapshot=snapshot,
                    walked=walked,
                )
            except IntegrityViolation as refusal:
                # A refusal here is the guard working: no allocation, a
                # consumed snapshot, a claim made on other data. Printed as
                # what it is rather than raised as a stack trace at somebody
                # who typed a command.
                console.print(f"[yellow]the walk did not run[/yellow] — {escape(str(refusal))}")
                raise typer.Exit(2) from None
    finally:
        runtime.close()

    console.print()
    console.print(f"[bold]{escape(walked.describe())}[/bold]")
    for note in walked.notes:
        console.print(f"  [dim]{escape(note)}[/dim]")

    if not gaps:
        console.print(
            "\n[yellow]no gap was measured[/yellow] — the walk produced no "
            "period the backtest also measured"
        )
        return

    table = Table(title="what the backtest claimed against what paper produced")
    for column in ("version", "metric", "backtest", "paper", "gap", "held"):
        table.add_column(column)
    for gap in gaps:
        neutral = gap.direction.value == "neutral"
        held = not neutral and gap.held
        table.add_row(
            gap.version_ref,
            gap.metric,
            str(gap.expected),
            str(gap.realised),
            f"[{'dim' if neutral else 'green' if held else 'red'}]{gap.gap:+}[/]",
            "—" if neutral else ("yes" if held else "no"),
        )
    console.print(table)
    console.print(
        "\n[dim]The walk read bars the research window stopped short of, and "
        "every order paid a spread, a fee and a size that rounds down to what "
        "Risk approved.[/dim]"
    )
    console.print(
        "[yellow]A gap this size is not an execution cost.[/yellow] [dim]The "
        "held-out window is a different stretch of market from the one the "
        "backtest read, so this number mixes how wrong the claim was with how "
        "different the two periods were. Telling those apart takes many "
        "deployments, which is why the mean gap is tracked as a company "
        "competence rather than read off one run.[/dim]"
    )
