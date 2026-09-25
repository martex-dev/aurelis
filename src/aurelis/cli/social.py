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


def _signed_in(context: object, pages: dict[str, object]) -> set[str]:
    """Which platforms the open profile is signed into right now."""
    done: set[str] = set()
    if "x" in pages:
        cookies = context.cookies("https://x.com")  # type: ignore[attr-defined]
        if any(c.get("name") == "auth_token" for c in cookies):
            done.add("x")
    if "discord" in pages:
        url = str(pages["discord"].url)  # type: ignore[attr-defined]
        if "discord.com/channels/" in url:
            done.add("discord")
    return done


@social_app.command("login")
def social_login(
    workspace: WorkspaceOption = None,
    platform: Annotated[
        list[str] | None,
        typer.Option(help="x, discord, or both (the default)."),
    ] = None,
    wait: Annotated[int, typer.Option(help="Minutes to wait for the sign-in.")] = 15,
) -> None:
    """Sign into X and Discord once, in Aurelis's own browser profile.

    Opens a Microsoft Edge window that uses only Aurelis's profile, on each
    site's sign-in page. Sign in there yourself; nothing is typed for you and
    no password is kept by Aurelis. When each site shows you signed in, close
    the window. From then on the service reads X and Discord through this
    profile, read-only.
    """
    import contextlib
    import datetime as dt
    import json
    import time

    from aurelis.core.config import load_settings
    from aurelis.intel.browser import LOGIN_PAGES, SIGNED_IN_MARK, profile_home

    wanted = [p.lower() for p in (platform or ["x", "discord"])]
    unknown = [p for p in wanted if p not in LOGIN_PAGES]
    if unknown:
        console.print(f"[red]no sign-in for {', '.join(unknown)}; one of x, discord[/red]")
        raise typer.Exit(1)
    settings = load_settings(home=workspace) if workspace else load_settings()
    home = profile_home(settings.workspace)
    home.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        console.print("[red]needs Playwright: `uv pip install playwright`[/red]")
        raise typer.Exit(1) from error

    console.print(
        "Opening Aurelis's own Edge window. Sign into "
        + " and ".join(wanted)
        + " there, then close the window. Your everyday browser is not touched."
    )
    signed: set[str] = set()
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(home),
            channel="msedge",
            headless=False,
            viewport=None,
            args=["--disable-blink-features=AutomationControlled"],
        )
        pages: dict[str, object] = {}
        for name in wanted:
            page = context.pages[0] if not pages and context.pages else context.new_page()
            page.goto(LOGIN_PAGES[name], wait_until="domcontentloaded")
            pages[name] = page
        deadline = time.monotonic() + wait * 60
        try:
            while time.monotonic() < deadline:
                try:
                    signed = _signed_in(context, pages) | signed
                except Exception:  # noqa: BLE001 - the window was closed
                    break
                if not context.pages:
                    break
                time.sleep(2)
        finally:
            # The window may already be closed; what was seen before stands.
            with contextlib.suppress(Exception):
                signed |= _signed_in(context, pages)
            with contextlib.suppress(Exception):
                context.close()
    mark = home / SIGNED_IN_MARK
    previous: list[str] = []
    if mark.exists():
        try:
            previous = list(json.loads(mark.read_text(encoding="utf-8")).get("platforms") or [])
        except (OSError, ValueError):
            previous = []
    platforms = sorted(set(previous) | signed)
    mark.write_text(
        json.dumps(
            {"platforms": platforms, "at": dt.datetime.now(dt.UTC).isoformat()}, indent=2
        ),
        encoding="utf-8",
    )
    for name in wanted:
        state = "[green]signed in[/green]" if name in signed else "[yellow]not signed in[/yellow]"
        console.print(f"{name}: {state}")
    if set(wanted) - signed:
        console.print("Run `aurelis social login` again for the ones not signed in.")


@social_app.command("list")
def social_list(workspace: WorkspaceOption = None) -> None:
    """Every handle the next wake reads, with where it came from."""
    from aurelis.social.curation import followed_targets

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            rows = followed_targets(session, at=runtime.clock.now())
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


@social_app.command("voices")
def social_voices(
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option(help="Voices shown, followed first.")] = 40,
) -> None:
    """Every voice's posts against the price move after and before them (M53)."""
    from aurelis.social.curation import followed_targets
    from aurelis.social.voices import measure_voices

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        with runtime.database.session() as session:
            now = runtime.clock.now()
            board = measure_voices(session, at=now, targets=followed_targets(session, at=now))
    finally:
        runtime.close()
    table = Table(title="voices against price: the 24h after each episode, against its peers")
    for column in ("voice", "followed", "episodes", "ahead", "after %", "p", "before", "verdict"):
        table.add_column(column, overflow="fold")
    for voice in board.voices[:limit]:
        table.add_row(
            escape(voice.key),
            escape(voice.origin or ""),
            str(voice.episodes),
            str(voice.ahead),
            "" if voice.after is None else f"{voice.after:+}",
            "" if voice.p_lead is None else str(voice.p_lead),
            f"{voice.before_ahead}/{voice.before_episodes}",
            escape(voice.verdict),
        )
    console.print(table)
    console.print(f"[dim]{escape(board.describe_bar())}. {len(board.voices)} voice(s) read.[/dim]")


@social_app.command("curate")
def social_curate(
    workspace: WorkspaceOption = None,
    agent: Annotated[
        str | None,
        typer.Option(
            help="The agent to seat. Defaults to the market-intelligence agent "
            "who has gone longest without curating."
        ),
    ] = None,
) -> None:
    """Seat an agent to follow and drop voices from their record. One model call."""
    from aurelis.social.curation import curate

    runtime = _runtime(workspace)
    try:
        runtime.initialise()
        outcome = curate(runtime, agent_handle=agent)
    finally:
        runtime.close()
    console.print(escape(outcome.describe()))
    if outcome.because:
        console.print(f"[dim]because: {escape(outcome.because)}[/dim]")
