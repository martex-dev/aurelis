"""``aurelis thesis`` — views sealed in advance, scored after, and the record.

Four commands, and the shape of them is the argument:

* ``seat`` puts an agent in the judgement seat. The agent picks the market.
* ``list`` shows every view, open ones with their horizon and settled ones
  with their score.
* ``resolve`` settles what a recording can settle. With ``--fetch --yes`` it
  first records the instruments whose horizons have passed, which is the one
  step here that reaches a market and is therefore typed on purpose.
* ``calibration`` reads the record: Brier, hit rate, and the gap between what
  each agent said and what happened, by confidence band.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

thesis_app = typer.Typer(
    help="Views agents sealed before the outcome existed, and how they scored.",
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
    from aurelis.judgement.standin import scripted_judge
    from aurelis.platform.llm.seating import seat_provider

    return Runtime.build(settings, provider=seat_provider(settings, scripted_judge))


@thesis_app.command("seat")
def thesis_seat(
    workspace: WorkspaceOption = None,
    agent: Annotated[
        list[str] | None,
        typer.Option(help="Agent handle(s) to seat. Repeatable. Default: INTEL."),
    ] = None,
) -> None:
    """Seat agents to choose a market and state a view, sealed in advance.

    Each agent is shown every recorded instrument it holds no open view on,
    picks one or declines, and then states a horizon, a direction and a
    confidence in its own words. The reply is figure-checked, the horizon is
    checked to lie ahead of the clock, and the row is hashed before it is
    written. Offline this seats a deterministic stand-in and says so.
    """
    from aurelis.judgement.seat import JudgementRefused, seat_agent
    from aurelis.platform.llm.seating import stands_in

    handles = agent or ["INTEL"]
    runtime = _runtime(workspace, seated=True)
    try:
        runtime.initialise()
        runtime.staff()
        results: list[tuple[str, str, str]] = []
        for handle in handles:
            try:
                sealed = seat_agent(runtime, agent_handle=handle)
            except JudgementRefused as error:
                results.append((handle, "refused", str(error)))
                continue
            if sealed is None:
                results.append((handle, "declined", "no view"))
            else:
                results.append((handle, "sealed", sealed.describe()))
        provider = runtime.settings.provider
    finally:
        runtime.close()

    table = Table(title="the judgement seat")
    for column in ("agent", "outcome", "what happened"):
        table.add_column(column, overflow="fold")
    for handle, outcome, detail in results:
        tone = {"sealed": "green", "refused": "red"}.get(outcome, "yellow")
        table.add_row(handle, f"[{tone}]{outcome}[/{tone}]", escape(detail))
    console.print(table)
    if stands_in(provider):
        console.print(
            "\n[dim]What sat in the seat is a deterministic stand-in, not a "
            "model: the provider is the offline mock. Point the workspace at a "
            "real provider and the same seat asks a real model.[/dim]"
        )
    console.print(
        "[dim]A sealed view is hashed and cannot be edited, rescored or "
        "deleted. It is scored once its horizon passes and a recording covers "
        "it: `aurelis thesis resolve`.[/dim]"
    )


@thesis_app.command("list")
def thesis_list(
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option(help="How many to show.")] = 40,
) -> None:
    """Every view, newest first: open ones with their horizon, scored ones with their score."""
    from aurelis.judgement.seat import verify_seal
    from aurelis.judgement.tables import Thesis

    runtime = _runtime(workspace)
    try:
        now = runtime.clock.now()
        with runtime.database.session() as session:
            rows = list(
                session.execute(
                    sa.select(Thesis)
                    .order_by(Thesis.sealed_at.desc(), Thesis.ref.desc())
                    .limit(limit)
                ).scalars()
            )
            table = Table(title="theses")
            for column in (
                "ref",
                "agent",
                "market",
                "view",
                "conf",
                "reference",
                "resolves",
                "outcome",
                "brier",
                "seal",
            ):
                table.add_column(column, overflow="fold")
            for row in rows:
                if row.scored_at is None:
                    left = row.resolves_at - now
                    hours = math.ceil(left.total_seconds() / 3600)
                    outcome = (
                        f"[yellow]open, {hours}h left[/yellow]"
                        if hours > 0
                        else "[yellow]due[/yellow]"
                    )
                    brier = "—"
                else:
                    hit = bool(row.outcome) == (row.direction == "up")
                    outcome = "[green]right[/green]" if hit else "[red]wrong[/red]"
                    brier = str(row.brier)
                table.add_row(
                    row.ref,
                    row.agent_ref,
                    f"{row.instrument}{'' if row.is_live else ' (fixture)'}",
                    f"{row.direction} {row.horizon_hours}h",
                    str(row.confidence),
                    row.reference_close,
                    row.resolves_at.strftime("%m-%d %H:%M"),
                    outcome,
                    brier,
                    "ok" if verify_seal(row) else "[red]BROKEN[/red]",
                )
    finally:
        runtime.close()
    console.print(table)
    if not rows:
        console.print("[dim]no view has been sealed yet: `aurelis thesis seat`[/dim]")


@thesis_app.command("resolve")
def thesis_resolve(
    workspace: WorkspaceOption = None,
    fetch: Annotated[
        bool, typer.Option("--fetch", help="Record the instruments with due views first.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Fetch without confirming.")] = False,
) -> None:
    """Score every view whose horizon has passed and a recording covers.

    Reads recordings only. ``--fetch`` records each instrument with a due view
    from the vendor first, which is the one thing here that reaches a market —
    so it asks, and ``--yes`` is the answer.
    """
    from aurelis.intel.live import CoinbaseCandles, FeedUnavailable, interval_seconds
    from aurelis.judgement.resolution import due, resolve_due

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        now = runtime.clock.now()
        if fetch:
            with runtime.database.session() as session:
                waiting = due(session, at=now)
                needed: dict[tuple[str, str, str], dt.datetime] = {}
                for row in waiting:
                    if not row.is_live:
                        continue
                    key = (row.desk, row.instrument, row.interval)
                    needed[key] = min(needed.get(key, row.resolves_at), row.resolves_at)
            if needed and not yes:
                console.print(
                    f"[yellow]This would fetch {len(needed)} instrument(s) from a "
                    "real market data endpoint.[/yellow] Re-run with --yes."
                )
                raise typer.Exit(code=1)
            feed = CoinbaseCandles()
            for (desk, symbol, interval), earliest in sorted(needed.items()):
                step = interval_seconds(interval)
                bars = int((now - earliest).total_seconds() // step) + 48
                with runtime.database.session() as session:
                    try:
                        snapshot = runtime.snapshots.ingest(
                            session, feed, desk=desk, symbol=symbol, interval=interval, bars=bars
                        )
                    except FeedUnavailable as error:
                        console.print(f"[red]{escape(symbol)}: {escape(str(error))}[/red]")
                        continue
                    console.print(
                        f"[dim]recorded {snapshot.ref}: {snapshot.bars} x {interval} of "
                        f"{symbol}, to {snapshot.last_at:%Y-%m-%d %H:%M}Z[/dim]"
                    )
        with runtime.database.session() as session:
            results = resolve_due(session, ledger=runtime.ledger, clock=runtime.clock, at=now)
    finally:
        runtime.close()

    table = Table(title="resolution")
    for column in ("ref", "agent", "market", "result", "detail"):
        table.add_column(column, overflow="fold")
    for result in results:
        if result.scored:
            mark = "[green]right[/green]" if result.hit else "[red]wrong[/red]"
            mark += f"  Brier {result.brier}"
        else:
            mark = "[yellow]pending[/yellow]"
        table.add_row(result.ref, result.agent_ref, result.instrument, mark, escape(result.detail))
    console.print(table)
    if not results:
        console.print("[dim]no view is due: every open horizon still lies ahead[/dim]")


@thesis_app.command("calibration")
def thesis_calibration(
    workspace: WorkspaceOption = None,
    fixtures: Annotated[
        bool, typer.Option("--fixtures", help="Include views made on fixture recordings.")
    ] = False,
) -> None:
    """The record, read whole: Brier, hit rate, and stated against observed by band."""
    from aurelis.judgement.calibration import COIN_TOSS, company_calibration

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            report = company_calibration(session, live_only=not fixtures)
    finally:
        runtime.close()

    for cut, label in (
        ("overall", "company"),
        ("by_agent", "by agent"),
        ("by_instrument", "by market"),
        ("by_horizon", "by horizon"),
    ):
        rows = report[cut]
        if cut != "overall" and not rows:
            continue
        table = Table(title=label)
        for column in ("", "sealed", "scored", "pending", "right", "brier", "base rate", "verdict"):
            table.add_column(column, overflow="fold")
        for record in rows:
            if not record.scored:
                verdict = "[dim]nothing scored yet[/dim]"
            elif record.beats_base_rate:
                verdict = "[green]beats the base rate[/green]"
            elif record.informative:
                verdict = "[yellow]beats a coin toss, not the base rate[/yellow]"
            else:
                verdict = "[red]no better than a coin toss[/red]"
            table.add_row(
                record.label,
                str(record.sealed),
                str(record.scored),
                str(record.pending),
                str(record.hit_rate) if record.hit_rate is not None else "—",
                str(record.mean_brier) if record.mean_brier is not None else "—",
                str(record.base_rate_brier) if record.base_rate_brier is not None else "—",
                verdict,
            )
        console.print(table)

    overall = report["overall"][0]
    if overall.scored:
        bands = Table(title="stated against observed, by confidence band")
        for column in ("band", "views", "said", "right", "over-confident by"):
            bands.add_column(column)
        for band in overall.bands:
            bands.add_row(
                f"{band.low}-{band.high}",
                str(band.n),
                str(band.stated) if band.stated is not None else "—",
                str(band.observed) if band.observed is not None else "—",
                str(band.gap) if band.gap is not None else "—",
            )
        console.print(bands)
    console.print(
        f"\n[dim]Brier: (p - outcome)^2, lower is better; {COIN_TOSS} is always saying "
        "50%. The base rate is what always predicting the observed up-frequency "
        "would have scored. A record that beats the coin toss but not the base "
        "rate has learned the drift of the market and nothing else."
        + (" Fixture views are excluded; --fixtures includes them." if not fixtures else "")
        + "[/dim]"
    )
