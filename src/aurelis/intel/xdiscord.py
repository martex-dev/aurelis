"""X accounts, X searches and Discord channels, read through the profile (M51).

Each reader opens one URL built from a validated handle and keeps the JSON
the site's own page fetched: X's timeline GraphQL responses, and Discord's
channel-messages responses. The parsers walk that JSON for the posts in it,
so a change in the shape around a post does not lose the post.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from aurelis.intel.live import FeedUnavailable
from aurelis.intel.social import Post
from aurelis.sources.catalogue import Source

__all__ = ["DiscordBrowser", "XBrowser", "discord_posts", "x_posts"]


# ------------------------------------------------------------------ X


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _x_time(text: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y").astimezone(dt.UTC)
    except (TypeError, ValueError):
        return None


def _screen_name(result: dict[str, Any]) -> str:
    user = ((result.get("core") or {}).get("user_results") or {}).get("result") or {}
    for place in (user.get("core") or {}, user.get("legacy") or {}):
        name = place.get("screen_name")
        if name:
            return str(name)
    return ""


def x_posts(bodies: list[Any], *, venue: str) -> list[Post]:
    """Every tweet in X's timeline JSON, once each, newest first."""
    seen: set[str] = set()
    out: list[Post] = []
    for body in bodies:
        for node in _walk(body):
            legacy = node.get("legacy")
            if not isinstance(legacy, dict):
                continue
            tweet_id = str(legacy.get("id_str") or node.get("rest_id") or "")
            if not tweet_id or "full_text" not in legacy or tweet_id in seen:
                continue
            seen.add(tweet_id)
            note = (
                ((node.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}
            ).get("text")
            author = _screen_name(node)
            out.append(
                Post(
                    id=f"x:{tweet_id}",
                    at=_x_time(str(legacy.get("created_at", ""))),
                    author=author,
                    text=str(note or legacy.get("full_text", "")),
                    url=f"https://x.com/{author or 'i'}/status/{tweet_id}",
                    likes=int(legacy.get("favorite_count") or 0),
                    reposts=int(legacy.get("retweet_count") or 0),
                    venue=venue,
                )
            )
    out.sort(key=lambda p: p.at or dt.datetime.min.replace(tzinfo=dt.UTC), reverse=True)
    return out


_SEARCH_OPERATIONS = ("/SearchTimeline",)


def _x_url(target: str) -> tuple[str, tuple[str, ...]]:
    """``$MOON`` or ``"bitcoin"`` is a live search; anything else an account,
    read as the live search ``from:<account>``.

    X's profile page stopped loading an account's posts for a headless reader
    by 2026-09-25: it fetched "who to follow" and nothing else. The live
    search for ``from:<account>`` answers with the account's newest posts
    through the same request as a cashtag search (M51).
    """
    if target.startswith("$") or target.startswith('"') or " " in target:
        query = target
    else:
        from aurelis.social.targets import normalise_handle

        query = f"from:{normalise_handle('x', target)}"
    encoded = urllib.parse.quote(query)
    return f"https://x.com/search?q={encoded}&src=typed_query&f=live", _SEARCH_OPERATIONS


@dataclass
class XBrowser:
    """An X account's newest posts, or a live search, through the profile."""

    source: Source
    opener: Any = None
    """A :class:`~aurelis.intel.browser.BrowserReader`; opened on first use."""

    _stack: Any = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.source.name

    def _reader(self) -> Any:
        if self.opener is None:
            from contextlib import ExitStack

            from aurelis.intel.browser import open_browser

            self._stack = ExitStack()
            self.opener = self._stack.enter_context(open_browser())
        return self.opener

    def posts(self, target: str) -> list[Post]:
        url, operations = _x_url(target)
        bodies = self._reader().capture(url, lambda u: any(op in u for op in operations))
        if not bodies:
            raise FeedUnavailable(f"x {target}: the page loaded no posts")
        return x_posts(bodies, venue=f"x/{target}")

    def close(self) -> None:
        if self._stack is not None:
            self._stack.close()
            self._stack = None
            self.opener = None


# ------------------------------------------------------------------ Discord


def _discord_time(text: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(dt.UTC)
    except (TypeError, ValueError):
        return None


def discord_posts(bodies: list[Any], *, channel: str) -> list[Post]:
    """Every message in Discord's channel-messages JSON, once each."""
    guild, _, channel_id = channel.partition("/")
    seen: set[str] = set()
    out: list[Post] = []
    for body in bodies:
        for message in body if isinstance(body, list) else []:
            if not isinstance(message, dict):
                continue
            message_id = str(message.get("id", ""))
            text = str(message.get("content") or "")
            for embed in message.get("embeds") or []:
                if isinstance(embed, dict):
                    text = " ".join(
                        p for p in (text, embed.get("title"), embed.get("description")) if p
                    )
            if not message_id or not text.strip() or message_id in seen:
                continue
            seen.add(message_id)
            author = message.get("author") or {}
            out.append(
                Post(
                    id=f"discord:{message_id}",
                    at=_discord_time(str(message.get("timestamp", ""))),
                    author=str(author.get("username", "")),
                    text=text.strip(),
                    url=f"https://discord.com/channels/{guild}/{channel_id}/{message_id}",
                    likes=sum(
                        int(r.get("count") or 0)
                        for r in message.get("reactions") or []
                        if isinstance(r, dict)
                    ),
                    venue=f"discord/{channel}",
                )
            )
    return out


@dataclass
class DiscordBrowser:
    """A Discord channel's newest messages, through the profile."""

    source: Source
    opener: Any = None
    _stack: Any = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.source.name

    def _reader(self) -> Any:
        if self.opener is None:
            from contextlib import ExitStack

            from aurelis.intel.browser import open_browser

            self._stack = ExitStack()
            self.opener = self._stack.enter_context(open_browser())
        return self.opener

    def posts(self, channel: str) -> list[Post]:
        from aurelis.social.targets import normalise_handle

        handle = normalise_handle("discord", channel)
        channel_id = handle.split("/")[1]
        bodies = self._reader().capture(
            f"https://discord.com/channels/{handle}",
            lambda u: f"/channels/{channel_id}/messages" in u,
        )
        if not bodies:
            raise FeedUnavailable(
                f"discord {handle}: no messages loaded; is the profile a member of the server?"
            )
        return discord_posts(bodies, channel=handle)

    def close(self) -> None:
        if self._stack is not None:
            self._stack.close()
            self._stack = None
            self.opener = None
