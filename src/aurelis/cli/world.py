"""``aurelis world`` — entities, events and relations."""

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

world_app = typer.Typer(
    help="The world model: what the company knows beyond a price series.",
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


@world_app.command("sync")
def world_sync(
    workspace: WorkspaceOption = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Reach the vendor without confirming.")
    ] = False,
) -> None:
    """Read the venue's product catalogue once and record what changed as events.

    Reaches a public endpoint; asks first. The service does this every wake
    under a grant; this is the same step, typed on purpose.
    """
    from aurelis.intel.live import FeedUnavailable
    from aurelis.world.sources import CoinbaseProducts, sync_catalogue

    if not yes:
        console.print(
            "[yellow]This reads the public Coinbase product catalogue.[/yellow] "
            "Re-run with --yes to proceed."
        )
        raise typer.Exit(code=1)
    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            try:
                synced = sync_catalogue(
                    session, runtime.world, CoinbaseProducts(), clock=runtime.clock
                )
            except FeedUnavailable as error:
                console.print(f"[red]Nothing was recorded.[/red] {escape(str(error))}")
                raise typer.Exit(code=1) from None
    finally:
        runtime.close()
    console.print(escape(synced.describe()))
    if synced.new_listings[:10]:
        console.print(f"[dim]new: {', '.join(synced.new_listings[:10])}[/dim]")


@world_app.command("derive")
def world_derive(
    workspace: WorkspaceOption = None,
    snapshot: Annotated[str, typer.Option(help="Recording to derive from; default newest.")] = "",
) -> None:
    """Derive notable-price events from a recording: volume spikes, range breaks."""
    from aurelis.intel.snapshots import MarketSnapshot, latest_snapshot
    from aurelis.world.derive import derive_price_events

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            row = (
                session.execute(
                    sa.select(MarketSnapshot).where(MarketSnapshot.ref == snapshot)
                ).scalar_one_or_none()
                if snapshot
                else latest_snapshot(session, live_only=False)
            )
            if row is None:
                console.print("[red]no recording to derive from[/red]")
                raise typer.Exit(code=1)
            new = derive_price_events(session, runtime.world, row)
            ref = row.ref
    finally:
        runtime.close()
    console.print(f"{ref}: {new} new event(s)")


@world_app.command("events")
def world_events(
    workspace: WorkspaceOption = None,
    entity: Annotated[str, typer.Option(help="instrument key, e.g. BTC-USD; blank for all.")] = "",
    limit: Annotated[int, typer.Option(help="How many to show.")] = 40,
) -> None:
    """Recent events, newest first."""
    from aurelis.world.store import World
    from aurelis.world.tables import WorldEvent

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            counts = World.counts(session)
            if entity:
                rows = World.events_for(
                    session, entity_kind="instrument", entity_key=entity, limit=limit
                )
            else:
                rows = list(
                    session.execute(
                        sa.select(WorldEvent).order_by(WorldEvent.at.desc()).limit(limit)
                    ).scalars()
                )
            table = Table(
                title=f"world: {counts['entities']} entities, {counts['events']} events, "
                f"{counts['relations']} relations"
            )
            for column in ("at", "kind", "entity", "payload", "source"):
                table.add_column(column, overflow="fold")
            for row in rows:
                table.add_row(
                    row.at.strftime("%m-%d %H:%M"),
                    row.kind,
                    f"{row.entity_kind}:{row.entity_key}",
                    escape(", ".join(f"{k} {v}" for k, v in sorted(row.payload.items()))[:120]),
                    escape(row.source[:50]),
                )
    finally:
        runtime.close()
    console.print(table)


@world_app.command("cooccur")
def world_cooccur(
    workspace: WorkspaceOption = None,
    first: Annotated[str, typer.Option(help="First event kind.")] = "price.volume_spike",
    second: Annotated[str, typer.Option(help="Second event kind.")] = "price.range_break",
    hours: Annotated[int, typer.Option(help="Window after the first, in hours.")] = 24,
) -> None:
    """Pairs of event kinds on the same entity inside a window. A list of
    conjunctions, not a discovery: it becomes one only when an agent states a
    mechanism that predicts something else, and that is tested."""
    import datetime as dt

    from aurelis.world.store import World

    runtime = _runtime(workspace)
    try:
        with runtime.database.session() as session:
            pairs = World.co_occurrences(
                session, first_kind=first, second_kind=second, within=dt.timedelta(hours=hours)
            )
            table = Table(title=f"{first} then {second} within {hours}h: {len(pairs)} pair(s)")
            for column in ("entity", "first at", "second at", "gap"):
                table.add_column(column)
            for pair in pairs[:60]:
                table.add_row(
                    f"{pair.entity_kind}:{pair.entity_key}",
                    pair.first.at.strftime("%m-%d %H:%M"),
                    pair.second.at.strftime("%m-%d %H:%M"),
                    str(pair.gap),
                )
    finally:
        runtime.close()
    console.print(table)
    console.print(
        "[dim]A conjunction is not a discovery. It becomes one when an agent states "
        "why it would work, who is on the other side, and what else the mechanism "
        "predicts -- and that is tested separately.[/dim]"
    )
