"""Telegram public channels, read through Telegram's own web preview (M50).

``https://t.me/s/<channel>`` is the page Telegram serves for any public
channel: the newest twenty or so messages, with each one's time and view
count, readable without an account. A *group* has no preview, so a group
cannot be read here; that needs a signed-in client.

Read-only by construction: the reader fetches one URL per channel, built
from a validated channel name, and never follows a link a message contains.
A message's text reaches the company as data and nothing else.
"""

from __future__ import annotations

import datetime as dt
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from aurelis.intel.live import FeedUnavailable
from aurelis.intel.social import Post
from aurelis.sources.catalogue import Source

__all__ = ["BROWSER_AGENT", "TelegramPublic", "parse_preview"]

BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
"""The preview is a web page for people; it answers a browser's agent."""


def _views(text: str) -> int:
    """``7.06K`` to ``7060``; ``1.2M`` to ``1200000``."""
    raw = text.strip().upper().replace(",", "")
    scale = 1
    if raw.endswith("K"):
        scale, raw = 1_000, raw[:-1]
    elif raw.endswith("M"):
        scale, raw = 1_000_000, raw[:-1]
    try:
        return int(float(raw) * scale)
    except ValueError:
        return 0


class _Preview(HTMLParser):
    """Collects each message's post id, text, time and views."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._text_depth = 0
        self._in_views = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "div" and "tgme_widget_message" in classes and attributes.get("data-post"):
            self._current = {"post": attributes["data-post"], "text": [], "at": None, "views": 0}
            self.messages.append(self._current)
            return
        if self._current is None:
            return
        if self._text_depth:
            if tag == "div":
                self._text_depth += 1
            elif tag == "br":
                self._current["text"].append("\n")
            return
        if tag == "div" and "tgme_widget_message_text" in classes:
            self._text_depth = 1
        elif tag == "span" and "tgme_widget_message_views" in classes:
            self._in_views = True
        elif tag == "time" and attributes.get("datetime") and self._current["at"] is None:
            self._current["at"] = attributes["datetime"]

    def handle_endtag(self, tag: str) -> None:
        if self._text_depth and tag == "div":
            self._text_depth -= 1
        if tag == "span":
            self._in_views = False

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._text_depth:
            self._current["text"].append(data)
        elif self._in_views:
            self._current["views"] = _views(data)


def parse_preview(html: str, channel: str) -> list[Post]:
    parser = _Preview()
    parser.feed(html)
    out: list[Post] = []
    for message in parser.messages:
        text = " ".join("".join(message["text"]).split())
        if not text:
            continue
        at: dt.datetime | None = None
        if message["at"]:
            try:
                at = dt.datetime.fromisoformat(str(message["at"])).astimezone(dt.UTC)
            except ValueError:
                at = None
        post = str(message["post"])
        out.append(
            Post(
                id=f"telegram:{post}",
                at=at,
                author=channel,
                text=text,
                url=f"https://t.me/{post}",
                likes=int(message["views"]),
                venue=f"telegram/{channel}",
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class TelegramPublic:
    """A public channel's newest messages. No account, no key."""

    source: Source
    timeout: int = 25
    opener: Any = None
    pause: float = 1.5
    """Seconds between channels: a few dozen pages an hour is a person's pace."""

    @property
    def name(self) -> str:
        return self.source.name

    def posts(self, channel: str) -> list[Post]:
        from aurelis.social.targets import normalise_handle

        handle = normalise_handle("telegram", channel)
        request = urllib.request.Request(
            f"https://t.me/s/{handle}",
            headers={"User-Agent": BROWSER_AGENT, "Accept": "text/html"},
        )
        if self.pause and self.opener is None:
            time.sleep(self.pause)
        fetch = self.opener or urllib.request.urlopen
        try:
            with fetch(request, timeout=self.timeout) as response:
                html = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            raise FeedUnavailable(
                f"telegram {handle} refused the request ({error.code})"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise FeedUnavailable(f"telegram {handle} could not be reached: {error}") from error
        posts = parse_preview(html, handle)
        if not posts and "tgme_widget_message" not in html:
            raise FeedUnavailable(
                f"telegram {handle} has no public preview: a group, a private channel, "
                "or no such channel"
            )
        return posts
