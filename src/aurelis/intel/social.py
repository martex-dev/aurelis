"""Social posts, from official read endpoints, recorded as events on instruments.

Three platforms answer on the catalogue's terms. **Stocktwits** publishes
each symbol's public message stream as JSON without a credential, and each
message carries the poster's own bullish or bearish tag. **Bluesky**'s
public app view answers a post search without a credential. **Reddit**'s
official API is free for an app a person registers, and reads with an
OAuth token the reader fetches from the app's client id and secret, which
live only in the service's environment.

A post becomes ``social.post`` on the instrument it names, at the post's
own time, keyed by the platform's id for the post, so the same post read on
ten wakes is one event. ``social.burst`` is derived by the one burst rule
(:mod:`aurelis.intel.bursts`). Nothing here scrapes a page, and nothing in
the test suite reaches the network: every reader takes an opener.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock
from aurelis.intel.bursts import derive_burst
from aurelis.intel.live import USER_AGENT, FeedUnavailable
from aurelis.intel.news import _TICKER_IS_A_WORD, ALIASES, mentions_of
from aurelis.sources.catalogue import KEY_PREFIX, Source
from aurelis.world.store import World

__all__ = [
    "BlueskySearch",
    "Post",
    "RedditListing",
    "StocktwitsStream",
    "bluesky_queries",
    "bluesky_query",
    "record_posts",
    "stocktwits_symbol",
]


@dataclass(frozen=True, slots=True)
class Post:
    """One public post, whatever the platform."""

    id: str
    at: dt.datetime | None
    author: str
    text: str
    url: str
    sentiment: str = ""
    """The poster's own tag where the platform has one: ``bullish``,
    ``bearish`` or empty. Never inferred here."""

    likes: int = 0
    reposts: int = 0
    venue: str = ""
    """A subreddit, a symbol stream: where on the platform it was posted."""


def _when(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return dt.datetime.fromtimestamp(float(value), tz=dt.UTC)
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _get_json(opener: Any, url: str, *, headers: dict[str, str], timeout: int, name: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    fetch = opener or urllib.request.urlopen
    try:
        with fetch(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise FeedUnavailable(f"{name} refused the request ({error.code})") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FeedUnavailable(f"{name} could not be reached: {error}") from error
    try:
        return json.loads(payload)
    except ValueError as error:
        raise FeedUnavailable(f"{name} answered with something that is not JSON") from error


# ------------------------------------------------------------------ Stocktwits


def stocktwits_symbol(instrument: str) -> str:
    """How Stocktwits names a followed instrument: a crypto pair's base with
    ``.X``, an equity ticker as it is."""
    if "-" in instrument:
        return f"{instrument.split('-', 1)[0].upper()}.X"
    return instrument.upper()


@dataclass(frozen=True, slots=True)
class StocktwitsStream:
    """``GET /api/2/streams/symbol/<symbol>.json``. No credential."""

    source: Source
    timeout: int = 25
    opener: Any = None

    @property
    def name(self) -> str:
        return self.source.name

    def posts(self, symbol: str) -> list[Post]:
        data = _get_json(
            self.opener,
            f"{self.source.url}{urllib.parse.quote(symbol)}.json",
            headers={"Accept": "application/json"},
            timeout=self.timeout,
            name=f"stocktwits {symbol}",
        )
        out: list[Post] = []
        for message in data.get("messages", []) or []:
            user = message.get("user") or {}
            sentiment = ((message.get("entities") or {}).get("sentiment") or {}).get("basic") or ""
            handle = str(user.get("username", ""))
            out.append(
                Post(
                    id=f"stocktwits:{message.get('id')}",
                    at=_when(message.get("created_at")),
                    author=handle,
                    text=str(message.get("body", "")),
                    url=f"https://stocktwits.com/{handle}/message/{message.get('id')}",
                    sentiment=str(sentiment).lower(),
                    likes=int(((message.get("likes") or {}).get("total")) or 0),
                    venue=symbol,
                )
            )
        return out


# ------------------------------------------------------------------ Bluesky


def bluesky_query(instrument: str) -> str:
    """The search that finds posts about an instrument: its cashtag, or its
    name for the tickers that are English words."""
    return bluesky_queries(instrument)[0]


def bluesky_queries(instrument: str) -> tuple[str, ...]:
    """Every search worth trying for an instrument, best first: the cashtag,
    then each name it is known by. The app view refuses some cashtags
    outright (``$ETH``, ``$DOGE``: "forbidden by administrative rules"),
    and the name still answers."""
    base = instrument.split("-", 1)[0].upper()
    names = tuple(f'"{alias}"' for alias in ALIASES.get(base, ()))
    if base in _TICKER_IS_A_WORD:
        return names or (f"${base}",)
    return (f"${base}", *names)


_BLUESKY_SESSION_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"
_BLUESKY_SIGNED_IN_URL = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"
_BLUESKY_SESSION: dict[str, str] = {}
"""Session tokens by handle, for the life of the process. In memory only."""


@dataclass(frozen=True, slots=True)
class BlueskySearch:
    """``app.bsky.feed.searchPosts``: anonymous on the public app view, or
    signed in with an app password a person supplies (M49).

    Anonymous search is partly refused by Bluesky's own rules: on 2026-09-25
    "bitcoin" answered and "arbitrum" got a 403, and the live wakes lost 26
    of 50 searches. A signed-in account is free and is answered in full. The
    handle and app password are read from the environment at fetch time,
    exchanged for a session token through the official
    ``com.atproto.server.createSession``, and never written anywhere.
    """

    source: Source
    timeout: int = 25
    opener: Any = None
    limit: int = 25

    @property
    def name(self) -> str:
        return self.source.name

    def _session(self, *, fresh: bool = False) -> str | None:
        """A session token for the supplied account, or ``None`` if none is."""
        handle = os.environ.get(f"{KEY_PREFIX}BLUESKY_HANDLE", "")
        password = os.environ.get(f"{KEY_PREFIX}BLUESKY_APP_PASSWORD", "")
        if not handle or not password:
            return None
        if not fresh and _BLUESKY_SESSION.get(handle):
            return _BLUESKY_SESSION[handle]
        request = urllib.request.Request(
            _BLUESKY_SESSION_URL,
            data=json.dumps({"identifier": handle, "password": password}).encode(),
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            method="POST",
        )
        fetch = self.opener or urllib.request.urlopen
        try:
            with fetch(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise FeedUnavailable(
                f"bluesky refused the supplied account's app password ({error.code})"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise FeedUnavailable(f"bluesky could not be reached for a session: {error}") from error
        token = str(data.get("accessJwt", ""))
        if not token:
            raise FeedUnavailable("bluesky issued no session for the supplied account")
        _BLUESKY_SESSION[handle] = token
        return token

    def posts(self, query: str) -> list[Post]:
        params = urllib.parse.urlencode({"q": query, "limit": self.limit, "sort": "latest"})
        token = self._session()
        if token is None:
            data = _get_json(
                self.opener,
                f"{self.source.url}?{params}",
                headers={"Accept": "application/json"},
                timeout=self.timeout,
                name=f"bluesky {query}",
            )
        else:
            url = f"{_BLUESKY_SIGNED_IN_URL}?{params}"
            try:
                data = _get_json(
                    self.opener,
                    url,
                    headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                    timeout=self.timeout,
                    name=f"bluesky {query}",
                )
            except FeedUnavailable as error:
                if "(400)" not in str(error) and "(401)" not in str(error):
                    raise
                # The session expired: one new one, one more try.
                token = self._session(fresh=True)
                data = _get_json(
                    self.opener,
                    url,
                    headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                    timeout=self.timeout,
                    name=f"bluesky {query}",
                )
        out: list[Post] = []
        for post in data.get("posts", []) or []:
            record = post.get("record") or {}
            author = post.get("author") or {}
            uri = str(post.get("uri", ""))
            handle = str(author.get("handle", ""))
            rkey = uri.rsplit("/", 1)[-1]
            out.append(
                Post(
                    id=uri,
                    at=_when(record.get("createdAt")) or _when(post.get("indexedAt")),
                    author=handle,
                    text=str(record.get("text", "")),
                    url=f"https://bsky.app/profile/{handle}/post/{rkey}",
                    likes=int(post.get("likeCount") or 0),
                    reposts=int(post.get("repostCount") or 0),
                    venue=query,
                )
            )
        return out


# ------------------------------------------------------------------ Reddit

_REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


@dataclass(frozen=True, slots=True)
class RedditListing:
    """A subreddit listing on the official OAuth API, with an app's own token.

    The client id and secret are read from the environment when a listing
    is fetched, never earlier and never into anything that is written down.
    A missing key is a :class:`FeedUnavailable` that names the variable.
    """

    source: Source
    timeout: int = 25
    opener: Any = None
    limit: int = 100

    @property
    def name(self) -> str:
        return self.source.name

    def _token(self) -> str:
        client_id = os.environ.get(f"{KEY_PREFIX}REDDIT_CLIENT_ID", "")
        secret = os.environ.get(f"{KEY_PREFIX}REDDIT_CLIENT_SECRET", "")
        if not client_id or not secret:
            raise FeedUnavailable(
                f"reddit needs {KEY_PREFIX}REDDIT_CLIENT_ID and "
                f"{KEY_PREFIX}REDDIT_CLIENT_SECRET in the service's environment"
            )
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        request = urllib.request.Request(
            _REDDIT_TOKEN_URL,
            data=b"grant_type=client_credentials",
            headers={"User-Agent": USER_AGENT, "Authorization": f"Basic {basic}"},
            method="POST",
        )
        fetch = self.opener or urllib.request.urlopen
        try:
            with fetch(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise FeedUnavailable(f"reddit refused the app's credentials ({error.code})") from error
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise FeedUnavailable(f"reddit could not be reached for a token: {error}") from error
        token = str(data.get("access_token", ""))
        if not token:
            raise FeedUnavailable("reddit issued no token for the app's credentials")
        return token

    def posts(self, listing_url: str | None = None) -> list[Post]:
        token = self._token()
        url = f"{listing_url or self.source.url}?limit={self.limit}&raw_json=1"
        data = _get_json(
            self.opener,
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=self.timeout,
            name=self.name,
        )
        out: list[Post] = []
        for child in (data.get("data") or {}).get("children") or []:
            item = child.get("data") or {}
            title = str(item.get("title", ""))
            body = str(item.get("selftext", ""))[:400]
            out.append(
                Post(
                    id=f"reddit:{item.get('name')}",
                    at=_when(item.get("created_utc")),
                    author=str(item.get("author", "")),
                    text=f"{title} {body}".strip(),
                    url=f"https://www.reddit.com{item.get('permalink', '')}",
                    likes=int(item.get("score") or 0),
                    reposts=int(item.get("num_comments") or 0),
                    venue=str(item.get("subreddit", "")),
                )
            )
        return out


# ------------------------------------------------------------------ recording


def record_posts(
    session: Session,
    world: World,
    artifacts: Any,
    *,
    source: Source,
    posts: list[Post],
    instruments: tuple[str, ...] | list[str],
    clock: Clock,
    at: dt.datetime | None = None,
    on: str | None = None,
) -> tuple[int, int]:
    """Record posts as ``social.post`` on instruments, then the bursts.

    ``on`` names the instrument the posts were fetched for (a symbol stream,
    a cashtag search), in which case every post lands on it; without it,
    each post lands on every followed instrument its text names. Returns
    ``(posts recorded, bursts recorded)``. A post with no time is skipped.
    The raw posts are stored once per fetch as an artifact.
    """
    moment = at or clock.now()
    raw = artifacts.put_json(
        session,
        {
            "source": source.name,
            "on": on,
            "at": moment.isoformat(),
            "posts": [
                {"id": p.id, "at": p.at.isoformat() if p.at else None, "author": p.author}
                for p in posts
            ],
        },
        kind="social.raw",
        produced_by=source.name,
    )
    world.see(
        session, kind="venue", key=source.name, name=source.name, source=source.url, at=moment
    )
    touched: set[str] = set()
    new = 0
    for post in posts:
        if post.at is None or post.at > moment:
            continue
        targets = [on] if on else mentions_of(post.text, instruments)
        for symbol in targets:
            _, created = world.record(
                session,
                kind="social.post",
                at=post.at,
                entity_kind="instrument",
                entity_key=symbol,
                payload={
                    "source": source.name,
                    "id": post.id[:120],
                    "author": post.author[:80],
                    "text": post.text[:200],
                    "url": post.url[:300],
                    "sentiment": post.sentiment,
                    "likes": post.likes,
                    "reposts": post.reposts,
                    "venue": post.venue[:80],
                },
                source=source.url,
                recorded_at=moment,
            )
            new += int(created)
            if created:
                touched.add(symbol)
    bursts = 0
    for symbol in sorted(touched):
        bursts += int(
            derive_burst(
                session,
                world,
                entity_kind="instrument",
                entity_key=symbol,
                kind_in="social.post",
                kind_out="social.burst",
                source=source.url,
                moment=moment,
                extra={"raw": raw.digest[:16]},
            )
        )
    return new, bursts
