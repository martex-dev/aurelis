"""``aurelis service`` — the company running for days.

``grant`` is the one step that needs a person: it records, once and on the
ledger, which vendor and which instruments the service may fetch on its own.
``start`` then wakes on an interval: fetch under the grants, settle every view
a recording covers, run the loop inside a daily model-call budget, and write
down what happened — including what broke. ``status`` reads the record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sqlalchemy as sa
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

service_app = typer.Typer(
    help="Run the company unattended: fetch under a grant, settle, work, record.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_INTERVALS = {"15m": 900, "30m": 1800, "1h": 3600, "6h": 21600, "1d": 86400}
_DURATIONS = {"1h": 3600, "6h": 21600, "1d": 86400, "3d": 259200, "7d": 604800, "30d": 2592000}


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings
    from aurelis.platform.llm.seating import seat_provider, standins

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings, provider=seat_provider(settings, standins()))


@service_app.command("grant")
def service_grant(
    workspace: WorkspaceOption = None,
    source: Annotated[str, typer.Option(help="coinbase, or fixture:<desk>.")] = "coinbase",
    desk: Annotated[str, typer.Option(help="Which desk the recordings belong to.")] = "crypto",
    instrument: Annotated[
        list[str] | None, typer.Option(help="Instrument to fetch. Repeatable.")
    ] = None,
    bars: Annotated[int, typer.Option(help="Bars per fetch.")] = 400,
    reason: Annotated[str, typer.Option(help="Why, in a sentence. Goes on the record.")] = "",
    by: Annotated[str, typer.Option(help="Who is granting this.")] = "OPERATOR",
    yes: Annotated[bool, typer.Option("--yes", help="Record without confirming.")] = False,
) -> None:
    """Record a standing permission for the service to fetch these instruments.

    This is the one decision a person makes. The service fetches nothing that
    is not on an active grant, the grant names who and why, and the database
    refuses to change it afterwards — only to revoke it.
    """
    instruments = tuple(instrument or [])
    if not instruments:
        console.print("[red]A grant names at least one --instrument.[/red]")
        raise typer.Exit(code=2)
    if len(reason) <= 10:
        console.print("[red]A grant says why, in a sentence: --reason.[/red]")
        raise typer.Exit(code=2)
    if not yes and not source.startswith("fixture:"):
        console.print(
            f"[yellow]This lets the service fetch {', '.join(instruments)} from "
            f"{escape(source)} on its own, every wake, until revoked.[/yellow] "
            "Re-run with --yes to record it."
        )
        raise typer.Exit(code=1)
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            row = runtime.grants.grant(
                session,
                source=source,
                desk=desk,
                instruments=instruments,
                granted_by=by,
                reason=reason,
                bars=bars,
            )
            ref = row.ref
    finally:
        runtime.close()
    console.print(
        f"[green]{ref}[/green] recorded: {escape(source)} {', '.join(instruments)} by {by}"
    )
    console.print("[dim]Revoke with `aurelis service revoke <ref>`. It cannot be edited.[/dim]")


@service_app.command("revoke")
def service_revoke(
    ref: Annotated[str, typer.Argument(help="Grant to revoke, e.g. GRT-0001.")],
    workspace: WorkspaceOption = None,
    by: Annotated[str, typer.Option(help="Who is revoking.")] = "OPERATOR",
) -> None:
    """Withdraw a grant. Written once; the row stays."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            runtime.grants.revoke(session, ref, by=by)
    finally:
        runtime.close()
    console.print(f"[green]{escape(ref)}[/green] revoked by {by}")


@service_app.command("start")
def service_start(
    workspace: WorkspaceOption = None,
    every: Annotated[str, typer.Option(help="Wake interval: 15m, 30m, 1h, 6h, 1d.")] = "1h",
    for_: Annotated[
        str, typer.Option("--for", help="How long to run: 1h, 6h, 1d, 3d, 7d, 30d.")
    ] = "1d",
    once: Annotated[bool, typer.Option("--once", help="One wake, then stop.")] = False,
    calls_per_day: Annotated[
        int, typer.Option(help="Model calls the service may spend in a rolling day.")
    ] = 200,
    snapshot: Annotated[
        str, typer.Option(help="Recording the loop's research actions measure on.")
    ] = "",
) -> None:
    """Wake on an interval: fetch, settle, work, record. Stops when told to.

    A vendor that is down or a model that is out of allowance is an alert on
    the record, not a crash: the service carries on and the next wake retries.
    It fetches only under an active grant and it cannot trade.
    """
    from aurelis.service.loop import Service, cycle_once, serve

    if every not in _INTERVALS:
        console.print(f"[red]Unknown interval {every!r}.[/red] Known: {', '.join(_INTERVALS)}")
        raise typer.Exit(code=2)
    if for_ not in _DURATIONS:
        console.print(f"[red]Unknown duration {for_!r}.[/red] Known: {', '.join(_DURATIONS)}")
        raise typer.Exit(code=2)

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        runtime.staff()
        source = _research_source(runtime, snapshot)
        service = Service(runtime, calls_per_day=calls_per_day, research_source=source)
        with runtime.database.session() as session:
            grants = runtime.grants.active(session)
        if not grants:
            console.print(
                "[yellow]No active data grant.[/yellow] The service will settle and work "
                "on what is already recorded, and fetch nothing. `aurelis service grant`."
            )
        if once:
            wake = cycle_once(runtime, service=service)
            console.print(escape(wake.describe()))
            return
        console.print(
            f"[bold]service[/bold] every {every} for {for_}, up to {calls_per_day} model "
            f"calls a day. Ctrl-C to stop. Nothing here can trade."
        )
        outcome = serve(
            runtime,
            interval_seconds=_INTERVALS[every],
            duration_seconds=_DURATIONS[for_],
            service=service,
        )
        console.print(escape(outcome.describe()))
    finally:
        runtime.close()


@service_app.command("status")
def service_status(workspace: WorkspaceOption = None) -> None:
    """Grants, the last wakes, and what broke."""
    from aurelis.alerts.tables import Alert
    from aurelis.service.tables import ServiceCycle

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            grants = runtime.grants.all(session)
            wakes = list(
                session.execute(
                    sa.select(ServiceCycle).order_by(ServiceCycle.started_at.desc()).limit(12)
                ).scalars()
            )
            open_alerts = list(
                session.execute(
                    sa.select(Alert)
                    .where(Alert.source.like("service.%"), Alert.resolved_at.is_(None))
                    .order_by(Alert.raised_at.desc())
                    .limit(12)
                ).scalars()
            )
            table = Table(title="data grants")
            for column in ("ref", "source", "desk", "instruments", "bars", "by", "state"):
                table.add_column(column, overflow="fold")
            for g in grants:
                table.add_row(
                    g.ref,
                    g.source,
                    g.desk,
                    ", ".join(map(str, g.instruments)),
                    str(g.bars),
                    g.granted_by,
                    "[green]active[/green]" if g.active else "[dim]revoked[/dim]",
                )
            console.print(table)
            walk = Table(title="last wakes")
            for column in (
                "ref",
                "at",
                "fetched",
                "scored",
                "pending",
                "run",
                "calls",
                "left",
                "incidents",
                "note",
            ):
                walk.add_column(column, overflow="fold")
            for w in wakes:
                walk.add_row(
                    w.ref,
                    w.started_at.strftime("%m-%d %H:%M"),
                    str(len(w.fetched)),
                    str(w.scored),
                    str(w.pending),
                    w.run_ref or "—",
                    str(w.calls),
                    str(w.calls_left_today),
                    str(len(w.incidents)),
                    escape(w.note[:60]),
                )
            console.print(walk)
            if open_alerts:
                broke = Table(title="what broke, still open")
                for column in ("ref", "severity", "source", "message"):
                    broke.add_column(column, overflow="fold")
                for a in open_alerts:
                    broke.add_row(a.ref, a.severity, a.source, escape(a.message[:100]))
                console.print(broke)
            else:
                console.print("[dim]no open service incident[/dim]")
    finally:
        runtime.close()


def _research_source(runtime: Runtime, ref: str) -> object | None:
    from aurelis.intel.snapshots import MarketSnapshot, SnapshotSource
    from aurelis.trading.paper import held_out

    with runtime.database.session() as session:
        query = sa.select(MarketSnapshot).where(MarketSnapshot.is_live.is_(True))
        if ref:
            query = query.where(MarketSnapshot.ref == ref)
        row = session.execute(
            query.order_by(MarketSnapshot.bars.desc(), MarketSnapshot.ref.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        return SnapshotSource(session, row, upto=held_out(row.bars))
