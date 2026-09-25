"""``aurelis social`` — whom the company follows on social platforms, and why."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.runtime import Runtime

console = Console()

social_app = typer.Typer(
    help="Social: the Telegram channels, X accounts and Discord channels the company follows.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]
PlatformArg = Annotated[str, typer.Argument(help="telegram, x or discord.")]
HandleArg = Annotated[
    str,
    typer.Argument(help="The channel or account: a name, an @name, or its link."),
]

OPERATOR = "operator"


def _runtime(workspace: Path | None) -> Runtime:
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    return Runtime.build(settings)


@social_app.command("follow")
def social_follow(
    platform: PlatformArg,
    handle: HandleArg,
    reason: Annotated[str, typer.Option(help="Why the company should read it.")],
    workspace: WorkspaceOption = None,
    on: Annotated[
        str | None,
        typer.Option(help="The instrument every post is about, if it is about one."),
    ] = None,
) -> None:
    """Follow a handle as the operator. Recorded with the reason; never edited."""
    from aurelis.social.targets import NotAHandle, follow_target

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            try:
                row = follow_target(
                    session,
                    platform=platform.lower(),
                    handle=handle,
                    reason=reason,
                    decided_by=OPERATOR,
                    on=on,
                    at=runtime.clock.now(),
                    ledger=runtime.ledger,
                )
            except (NotAHandle, ValueError) as error:
                console.print(f"[red]{escape(str(error))}[/red]")
                raise typer.Exit(1) from error
            ref, shown = row.ref, f"{row.platform}:{row.handle}"
    finally:
        runtime.close()
    console.print(f"{ref}: following {escape(shown)}. The next wake reads it.")


@social_app.command("drop")
def social_drop(
    platform: PlatformArg,
    handle: HandleArg,
    reason: Annotated[str, typer.Option(help="Why the company should stop reading it.")],
    workspace: WorkspaceOption = None,
) -> None:
    """Stop following a handle. Also overrides a token's own link to it."""
    from aurelis.social.targets import NotAHandle, drop_target

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            try:
                row = drop_target(
                    session,
                    platform=platform.lower(),
                    handle=handle,
                    reason=reason,
                    decided_by=OPERATOR,
                    at=runtime.clock.now(),
                    ledger=runtime.ledger,
                )
            except (NotAHandle, ValueError) as error:
                console.print(f"[red]{escape(str(error))}[/red]")
                raise typer.Exit(1) from error
            ref, shown = row.ref, f"{row.platform}:{row.handle}"
    finally:
        runtime.close()
    console.print(f"{ref}: dropped {escape(shown)}.")


@social_app.command("list")
def social_list(workspace: WorkspaceOption = None) -> None:
    """Every handle the next wake reads, with where it came from."""
    from aurelis.intel.dex import DexRule, followed_tokens
    from aurelis.service.grants import Grants
    from aurelis.social.targets import active_targets

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            tokens: list[str] = []
            for grant in Grants.active(session):
                if grant.is_dex:
                    rule = DexRule.parse(grant.rule, tuple(str(n) for n in grant.instruments))
                    tokens += [
                        k for k, _ in followed_tokens(session, rule=rule, at=runtime.clock.now())
                    ]
            rows = active_targets(session, tokens=tuple(tokens))
    finally:
        runtime.close()
    table = Table(title="social targets the next wake reads")
    for column in ("platform", "handle", "about", "from", "why"):
        table.add_column(column, overflow="fold")
    for target in rows:
        table.add_row(
            target.platform,
            escape(target.handle),
            escape(target.on or "whatever it names"),
            escape(target.origin),
            escape(target.reason),
        )
    console.print(table)
    console.print(
        "[dim]A followed memecoin's own X account and Telegram channel are followed "
        "while the token is. Telegram channels are read through their public preview; "
        "X and Discord are read once a person has signed in (`aurelis social login`, "
        "M51).[/dim]"
    )
