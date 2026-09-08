"""``aurelis data`` — bringing a real market into the record, once.

The only command in this repository that reaches a market. It is separate for
the same reason ``aurelis model check`` is: everything else runs offline, and
the one thing that does not should be something a person types on purpose.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.intel.live import COINBASE_GRANULARITIES, CoinbaseCandles, FeedUnavailable
from aurelis.intel.snapshots import MarketSnapshot, latest_snapshot
from aurelis.runtime import Runtime

console = Console()

data_app = typer.Typer(
    help="Market data: what the company has actually seen.",
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


@data_app.command("fetch")
def data_fetch(
    workspace: WorkspaceOption = None,
    symbol: Annotated[str, typer.Option(help="Vendor product, e.g. BTC-USD.")] = "BTC-USD",
    desk: Annotated[str, typer.Option(help="Which desk the data belongs to.")] = "crypto",
    interval: Annotated[str, typer.Option(help="Bar width.")] = "1h",
    bars: Annotated[int, typer.Option(help="How many bars to record.")] = 2000,
    yes: Annotated[
        bool, typer.Option("--yes", help="Fetch without confirming.")
    ] = False,
) -> None:
    """Fetch real candles once and freeze them into a hashed snapshot.

    **The snapshot is what research runs against, not the feed.** An experiment
    cannot be reproduced against a moving endpoint, and every preregistration
    here locks a spec whose data fingerprint has to still mean something
    tomorrow. So the fetch is an event with a record, and everything after it
    reads the recording.
    """
    if interval not in COINBASE_GRANULARITIES:
        console.print(
            f"[red]Unknown interval {interval!r}.[/red] Known: "
            f"{', '.join(sorted(COINBASE_GRANULARITIES))}"
        )
        raise typer.Exit(code=1)

    feed = CoinbaseCandles()
    console.print(f"[bold]vendor[/bold]    {feed.name}  {feed.endpoint}")
    console.print(f"[bold]asking[/bold]    {bars} x {interval} of {symbol}")
    if not yes:
        console.print(
            "\n[yellow]This reaches a real market data endpoint.[/yellow] It is "
            "public and unauthenticated, and nothing is sent but the request. "
            "Re-run with --yes to proceed."
        )
        raise typer.Exit(code=1)

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            try:
                snapshot = runtime.snapshots.ingest(
                    session,
                    feed,
                    desk=desk,
                    symbol=symbol,
                    interval=interval,
                    bars=bars,
                )
            except FeedUnavailable as error:
                console.print(f"\n[red]No data was stored.[/red] {escape(str(error))}")
                raise typer.Exit(code=1) from None
            ok, detail = runtime.snapshots.verify(session, snapshot.ref)
            ref = snapshot.ref
            summary = _summary(snapshot)
    finally:
        runtime.close()

    console.print()
    console.print(_table(summary, title=f"{ref} — recorded"))
    console.print()
    console.print(
        f"[green]{detail}[/green]" if ok else f"[red]{detail}[/red]"
    )
    console.print(
        "\n[dim]A snapshot is a recording, not a connection. The company has "
        "seen this market as of the fetch time above and knows nothing about "
        "what the price is now. Research runs against the recording, which is "
        "what makes an experiment reproducible.[/dim]"
    )


@data_app.command("snapshots")
def data_snapshots(workspace: WorkspaceOption = None) -> None:
    """What real market data the company holds, if any."""
    import sqlalchemy as sa

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            rows = list(
                session.execute(
                    sa.select(MarketSnapshot).order_by(MarketSnapshot.ref)
                ).scalars()
            )
            checks = {row.ref: runtime.snapshots.verify(session, row.ref) for row in rows}
    finally:
        runtime.close()

    if not rows:
        console.print(
            "[yellow]The company has never seen a market.[/yellow] Every number "
            "it holds was computed on a fixture. `aurelis data fetch --yes` "
            "changes that."
        )
        return

    table = Table(title="market snapshots")
    for column in ("ref", "source", "symbol", "interval", "bars", "window", "digest", "verifies"):
        table.add_column(column, overflow="fold")
    for row in rows:
        ok, _ = checks[row.ref]
        table.add_row(
            row.ref,
            row.source if row.is_live else f"{row.source} (not live)",
            row.symbol,
            row.interval,
            str(row.bars),
            f"{row.first_at:%Y-%m-%d} to {row.last_at:%Y-%m-%d}",
            row.digest[:12],
            "[green]yes[/green]" if ok else "[red]NO[/red]",
        )
    console.print(table)


@data_app.command("show")
def data_show(
    workspace: WorkspaceOption = None,
    ref: Annotated[str, typer.Option(help="Snapshot, e.g. SNP-0001.")] = "",
) -> None:
    """One snapshot, and whether its bars still hash to what was recorded."""
    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            snapshot = (
                runtime.snapshots.get(session, ref)
                if ref
                else latest_snapshot(session, live_only=False)
            )
            if snapshot is None:
                console.print("[yellow]No snapshot has been ingested.[/yellow]")
                raise typer.Exit(code=1)
            ok, detail = runtime.snapshots.verify(session, snapshot.ref)
            bars = runtime.snapshots.bars_of(session, snapshot.ref)
            summary = _summary(snapshot)
    finally:
        runtime.close()

    console.print(_table(summary, title=summary["ref"]))
    if bars:
        recent = Table(title="the last five bars recorded")
        for column in ("time", "open", "high", "low", "close", "volume"):
            recent.add_column(column)
        for bar in bars[-5:]:
            recent.add_row(
                f"{bar.timestamp:%Y-%m-%d %H:%M}",
                str(bar.open),
                str(bar.high),
                str(bar.low),
                str(bar.close),
                str(bar.volume),
            )
        console.print(recent)
    console.print(f"[green]{detail}[/green]" if ok else f"[red]{detail}[/red]")


def _summary(snapshot: MarketSnapshot) -> dict[str, str]:
    return {
        "ref": snapshot.ref,
        "source": snapshot.source,
        "endpoint": snapshot.endpoint,
        "symbol": snapshot.symbol,
        "interval": snapshot.interval,
        "bars": str(snapshot.bars),
        "first bar": snapshot.first_at.isoformat(),
        "last bar": snapshot.last_at.isoformat(),
        "digest": snapshot.digest,
        "live market": "yes" if snapshot.is_live else "no",
        "fetched at": snapshot.fetched_at.isoformat(),
    }


def _table(summary: dict[str, str], *, title: str) -> Table:
    table = Table(title=title, show_header=False, box=None)
    table.add_column("", style="bold", width=14)
    table.add_column("")
    for key, value in summary.items():
        table.add_row(key, escape(str(value)))
    return table
