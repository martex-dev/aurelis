"""``aurelis trading`` — the paper book, the chain behind it, and the gap.

``chain`` is the command worth having: given an order, it walks backwards to
the approval, the assessment and the proposal that produced it, and prints the
three numbers. If any link were missing the order could not exist, so the
output is a demonstration rather than a report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.risk.tables import RiskAssessment, TradeApproval, TradeProposal
from aurelis.runtime import Runtime
from aurelis.trading.posttrade import DIRECTIONS, Direction
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

