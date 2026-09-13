"""Reading one catalogue source, whatever its kind, in two steps.

The service fetches outside a database session and records inside one, so
a reader that makes thirty requests does not hold the file lock for the
thirty seconds they take. :func:`fetch_source` is the network step and
returns what came back; :func:`record_source` is the record step and
returns how many events and bursts were written. The dispatch on the
source's kind is here and nowhere else.

A source read per instrument fails per instrument: a symbol the platform
does not list is a 404 for that symbol, not a reason to drop the other
twenty-nine. The failures come back by instrument, the wake names them,
and only a source that failed on every instrument is an incident.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock
from aurelis.intel.live import FeedUnavailable
from aurelis.sources.catalogue import Source
from aurelis.world.store import World

__all__ = ["Fetched", "fetch_source", "record_source"]


@dataclass(frozen=True, slots=True)
class Fetched:
    """What a fetch brought back, by kind. Only one payload field is set."""

    source: Source
    entries: list[Any] = field(default_factory=list)
    posts_on: dict[str, list[Any]] = field(default_factory=dict)
    """Posts fetched per instrument: a symbol stream, a cashtag search."""

    posts: list[Any] = field(default_factory=list)
    """Posts fetched for no instrument in particular: a subreddit."""

    boosts: Any = None
    trending: dict[str, list[Any]] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    """Instruments (or networks) the reader could not read, and why."""

    @property
    def requests(self) -> int:
        """How many reads succeeded: one per instrument or network, else one."""
        if self.posts_on:
            return len(self.posts_on)
        if self.trending:
            return len(self.trending)
        return 1

    def describe_failures(self) -> str:
        if not self.failures:
            return ""
        shown = "; ".join(f"{k}: {v}" for k, v in sorted(self.failures.items())[:3])
        more = len(self.failures) - 3
        return shown + (f"; and {more} more" if more > 0 else "")


def _per_instrument(
    source: Source,
    feed: Any,
    instruments: tuple[str, ...],
    query: Any,
    names: dict[str, str] | None = None,
) -> Fetched:
    posts_on: dict[str, list[Any]] = {}
    failures: dict[str, str] = {}
    for instrument in instruments:
        asked = instrument
        if ":" in instrument:
            # A token keyed by chain and contract is searched by its ticker,
            # as a crypto pair would be; a token nobody has named yet is not
            # searched at all, and the wake says so.
            ticker = (names or {}).get(instrument)
            if not ticker:
                failures[instrument] = "no ticker for this token yet; not searched"
                continue
            asked = f"{ticker}-USD"
        alternatives = query(asked)
        if isinstance(alternatives, str):
            alternatives = (alternatives,)
        last = ""
        for attempt in alternatives:
            try:
                posts_on[instrument] = list(feed.posts(attempt))
                break
            except FeedUnavailable as error:
                last = str(error)[:120]
        else:
            failures[instrument] = last
    if instruments and not posts_on:
        raise FeedUnavailable(
            f"{source.name} failed on every instrument; first: {next(iter(failures.values()))}"
        )
    return Fetched(source, posts_on=posts_on, failures=failures)


def fetch_source(
    source: Source,
    feed: Any,
    instruments: tuple[str, ...],
    *,
    names: dict[str, str] | None = None,
) -> Fetched:
    """The network step. Raises :class:`FeedUnavailable` as the reader does,
    except per instrument, where it collects. ``names`` gives a token keyed
    by chain and contract the ticker a social reader searches by."""
    kind = source.kind
    if kind in ("rss", "cryptopanic"):
        return Fetched(source, entries=list(feed.entries()))
    if kind == "stocktwits":
        from aurelis.intel.social import stocktwits_symbol

        return _per_instrument(source, feed, instruments, stocktwits_symbol, names)
    if kind == "bluesky":
        from aurelis.intel.social import bluesky_queries

        return _per_instrument(source, feed, instruments, bluesky_queries, names)
    if kind == "reddit":
        return Fetched(source, posts=list(feed.posts(source.url)))
    if kind == "dexscreener":
        from aurelis.intel.onchain import fetch_boosts

        return Fetched(source, boosts=fetch_boosts(feed))
    if kind == "geckoterminal":
        from aurelis.intel.onchain import NETWORKS

        trending: dict[str, list[Any]] = {}
        failures: dict[str, str] = {}
        for network in NETWORKS:
            try:
                trending[network] = list(feed.trending(network))
            except FeedUnavailable as error:
                failures[network] = str(error)[:120]
        if not trending:
            raise FeedUnavailable(
                f"{source.name} failed on every network; first: {next(iter(failures.values()))}"
            )
        return Fetched(source, trending=trending, failures=failures)
    raise ValueError(f"no reader for source kind {kind!r}")


def record_source(
    session: Session,
    world: World,
    artifacts: Any,
    *,
    fetched: Fetched,
    instruments: tuple[str, ...],
    clock: Clock,
    at: dt.datetime | None = None,
) -> tuple[int, int]:
    """The record step: ``(events recorded, bursts recorded)``."""
    source = fetched.source
    kind = source.kind
    if kind in ("rss", "cryptopanic"):
        from aurelis.intel.news import record_news

        return record_news(
            session,
            world,
            artifacts,
            source=source,
            entries=fetched.entries,
            instruments=instruments,
            clock=clock,
            at=at,
        )
    if kind in ("stocktwits", "bluesky"):
        from aurelis.intel.social import record_posts

        events = bursts = 0
        for instrument, posts in fetched.posts_on.items():
            new, burst = record_posts(
                session,
                world,
                artifacts,
                source=source,
                posts=posts,
                instruments=instruments,
                clock=clock,
                at=at,
                on=instrument,
            )
            events += new
            bursts += burst
        return events, bursts
    if kind == "reddit":
        from aurelis.intel.social import record_posts

        return record_posts(
            session,
            world,
            artifacts,
            source=source,
            posts=fetched.posts,
            instruments=instruments,
            clock=clock,
            at=at,
        )
    if kind == "dexscreener":
        from aurelis.intel.onchain import record_boosts

        return record_boosts(
            session, world, artifacts, source=source, fetched=fetched.boosts, clock=clock, at=at
        )
    if kind == "geckoterminal":
        from aurelis.intel.onchain import record_trending

        return record_trending(
            session, world, artifacts, source=source, fetched=fetched.trending, clock=clock, at=at
        )
    raise ValueError(f"no recorder for source kind {kind!r}")
