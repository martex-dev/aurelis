"""Reading X and Discord through a browser profile the operator signed into (M51).

X and Discord have no free read API. The operator asked that the agents read
them through this machine and accepted the ban risk (ADR-0051). The design
keeps that safe for the operator:

* **A dedicated profile.** ``<workspace>/browser`` is an Edge profile used
  only by Aurelis. The operator signs into X and Discord in it once with
  ``aurelis social login``. The everyday browser, its passwords, its email
  and its bank sessions are never opened.
* **Read-only by construction.** A reader opens only a URL it built from a
  validated handle (an X account, an X search, a Discord channel), waits for
  the page to load the posts, and keeps the JSON the site's own page fetched.
  There is no click, no typing, no scroll that loads a composer, and no code
  path that posts, likes, joins or sends. A link inside a post is never
  opened.
* **No model drives it.** The agents choose what is read; this code reads it.

Nothing here stores a password or a token. The profile holds the site's own
session cookie, as any browser does, inside the workspace folder that git
ignores.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from aurelis.intel.live import FeedUnavailable

__all__ = [
    "LOGIN_PAGES",
    "PROFILE_DIR",
    "SIGNED_IN_MARK",
    "BrowserReader",
    "browser_ready",
    "configure",
    "open_browser",
    "profile_home",
]

PROFILE_DIR = "browser"
"""The profile folder, under the workspace. Aurelis's alone."""

SIGNED_IN_MARK = "signed-in.json"
"""Written by ``aurelis social login`` once the operator finished signing in:
which platforms, and when. No credential is in it."""

LOGIN_PAGES: dict[str, str] = {
    "x": "https://x.com/i/flow/login",
    "discord": "https://discord.com/login",
}

_HOME: dict[str, Path] = {}


def configure(workspace: Path) -> None:
    """Tell the readers which workspace's profile to use. The service calls
    this once when it starts."""
    _HOME["workspace"] = Path(workspace)


def profile_home(workspace: Path | None = None) -> Path:
    base = Path(workspace) if workspace is not None else _HOME.get("workspace")
    if base is None:
        raise FeedUnavailable("no workspace configured for the browser profile")
    return base / PROFILE_DIR


def browser_ready(platform: str, workspace: Path | None = None) -> bool:
    """Whether the operator has signed into ``platform`` in the profile."""
    try:
        mark = profile_home(workspace) / SIGNED_IN_MARK
    except FeedUnavailable:
        return False
    if not mark.exists():
        return False
    try:
        signed = json.loads(mark.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return platform in (signed.get("platforms") or [])


class BrowserReader:
    """One open profile. Opens a URL and keeps the JSON the page fetched."""

    def __init__(self, context: Any) -> None:
        self._context = context

    def capture(
        self,
        url: str,
        wanted: Callable[[str], bool],
        *,
        wait_ms: int = 7000,
        settle_ms: int = 1500,
    ) -> list[Any]:
        """Open ``url``; return every JSON body of a response whose URL
        ``wanted`` accepts, in arrival order. Only GET responses count."""
        bodies: list[Any] = []
        page = self._context.new_page()

        def keep(response: Any) -> None:
            try:
                if response.request.method != "GET" or not wanted(response.url):
                    return
                bodies.append(response.json())
            except Exception:  # noqa: BLE001 - a body that is not JSON is not a post
                return

        page.on("response", keep)
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            except Exception as error:  # noqa: BLE001 - the site refused or timed out
                raise FeedUnavailable(f"{url} did not load: {str(error)[:120]}") from error
            waited = 0
            while waited < wait_ms:
                page.wait_for_timeout(500)
                waited += 500
                if bodies and waited >= settle_ms:
                    break
            if "/login" in page.url or "/i/flow/login" in page.url:
                raise FeedUnavailable(
                    f"{url} sent the profile to a sign-in page; run `aurelis social login`"
                )
        finally:
            page.close()
        return bodies


@contextmanager
def open_browser(
    workspace: Path | None = None, *, headless: bool | None = None
) -> Iterator[BrowserReader]:
    """The Aurelis profile in Microsoft Edge, for the length of one wake."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise FeedUnavailable(
            "the browser readers need Playwright: `uv pip install playwright`"
        ) from error
    home = profile_home(workspace)
    home.mkdir(parents=True, exist_ok=True)
    hidden = (
        headless
        if headless is not None
        else os.environ.get("AURELIS_BROWSER_HEADED", "") not in ("1", "true", "yes")
    )
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(home),
                channel="msedge",
                headless=hidden,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as error:  # noqa: BLE001 - Edge missing, or the profile in use
            raise FeedUnavailable(f"the Aurelis browser could not start: {error}") from error
        try:
            yield BrowserReader(context)
        finally:
            context.close()
