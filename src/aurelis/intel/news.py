"""Headlines from official feeds, recorded as events on instruments.

The brief names social posts and news as raw material for the mechanisms the
company should be able to state, and the operator's constraint is that every
source be official and free. Publishers' own RSS feeds are the outlet's
official syndication, public, and rate-limited only by courtesy; an
aggregator's developer API is free with a token a person supplies. The
catalogue of all of them, for every market, is :mod:`aurelis.sources.catalogue`;
this module reads the headline kinds. Nothing here scrapes a page.

Which sources the company reads is not decided here. An agent from Market
Intelligence is shown the catalogue and the instruments the company follows,
chooses, and says why (:mod:`aurelis.sources.seat`); the service reads what
was chosen, under a grant a person recorded once for the source class.

A headline becomes ``news.mention`` on every instrument it names, at the
headline's own published time, so mining can join it to price events on the
same entity and a mechanism can seal against the spot close. ``news.burst``
is derived when an instrument's mentions over the last six hours are both
several and several times its trailing week's rate; the threshold travels in
the event.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock
from aurelis.intel.bursts import BURST_FACTOR, BURST_MIN, derive_burst
from aurelis.intel.live import USER_AGENT, FeedUnavailable
from aurelis.sources.catalogue import CATALOGUE, KEY_PREFIX, Source
from aurelis.world.store import World

__all__ = [
    "BURST_FACTOR",
    "BURST_MIN",
    "CATALOGUE",
    "CryptoPanicFeed",
    "Entry",
    "RssFeed",
    "Source",
    "mentions_of",
    "record_news",
]




ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("bitcoin",),
    "ETH": ("ethereum", "ether"),
    "SOL": ("solana",),
    "XRP": ("xrp", "ripple"),
    "ADA": ("cardano",),
    "DOGE": ("dogecoin",),
    "LINK": ("chainlink",),
    "DOT": ("polkadot",),
    "AVAX": ("avalanche",),
    "LTC": ("litecoin",),
    "BCH": ("bitcoin cash",),
    "UNI": ("uniswap",),
    "SUI": ("sui network", "sui blockchain"),
    "NEAR": ("near protocol",),
    "HBAR": ("hedera",),
    "XLM": ("stellar lumens", "stellar"),
    "BNB": ("binance coin", "bnb chain"),
    "TAO": ("bittensor",),
    "ARB": ("arbitrum",),
    "ONDO": ("ondo finance",),
    "ENA": ("ethena",),
    "ZEC": ("zcash",),
    "HYPE": ("hyperliquid",),
    "AAVE": ("aave",),
    "PEPE": ("pepe coin", "pepecoin"),
    "SHIB": ("shiba inu",),
    "TRUMP": ("trump coin", "trump memecoin", "$trump"),
    "PUMP": ("pump.fun",),
    "USELESS": ("useless coin",),
}
"""How an asset is named in prose. The ticker itself matches only as an
upper-case word, and not at all for the tickers that are English words."""

_TICKER_IS_A_WORD: frozenset[str] = frozenset({"NEAR", "PUMP", "TRUMP", "USELESS", "SUI", "LINK"})


@dataclass(frozen=True, slots=True)
class Entry:
    title: str
    link: str
    published: dt.datetime | None
    summary: str


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _when(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def parse_rss(payload: bytes) -> list[Entry]:
    """RSS 2.0 items and Atom entries, title, link, published, summary."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise FeedUnavailable(f"the feed is not well-formed XML: {error}") from error
    entries: list[Entry] = []
    for item in root.iter("item"):
        entries.append(
            Entry(
                title=_strip_tags(_text(item.find("title"))),
                link=_text(item.find("link")),
                published=_when(
                    _text(item.find("pubDate"))
                    or _text(item.find("{http://purl.org/dc/elements/1.1/}date"))
                ),
                summary=_strip_tags(_text(item.find("description")))[:400],
            )
        )
    atom = "{http://www.w3.org/2005/Atom}"
    for item in root.iter(f"{atom}entry"):
        link = item.find(f"{atom}link")
        entries.append(
            Entry(
                title=_strip_tags(_text(item.find(f"{atom}title"))),
                link=(link.get("href") or "") if link is not None else "",
                published=_when(
                    _text(item.find(f"{atom}published")) or _text(item.find(f"{atom}updated"))
                ),
                summary=_strip_tags(_text(item.find(f"{atom}summary")))[:400],
            )
        )
    return [e for e in entries if e.title]


@dataclass(frozen=True, slots=True)
class RssFeed:
    """One catalogue source, fetched with an injectable opener."""

    source: Source
    timeout: int = 25
    opener: Any = None

    @property
    def name(self) -> str:
        return self.source.name

    def entries(self) -> list[Entry]:
        request = urllib.request.Request(self.source.url, headers={"User-Agent": USER_AGENT})
        fetch = self.opener or urllib.request.urlopen
        try:
            with fetch(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            raise FeedUnavailable(f"{self.name} refused the request ({error.code})") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise FeedUnavailable(f"{self.name} could not be reached: {error}") from error
        return parse_rss(payload)


def mentions_of(text: str, instruments: tuple[str, ...] | list[str]) -> list[str]:
    """Which of these spot instruments a headline names, by ticker or alias."""
    lowered = text.lower()
    found: list[str] = []
    for symbol in instruments:
        base = str(symbol).split("-", 1)[0].upper()
        hit = False
        if base not in _TICKER_IS_A_WORD and re.search(
            rf"(?<![A-Za-z0-9$]){re.escape(base)}(?![A-Za-z0-9])", text
        ):
            hit = True
        if not hit:
            for alias in ALIASES.get(base, ()):
                if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered):
                    hit = True
                    break
        if hit:
            found.append(str(symbol))
    return found


def record_news(
    session: Session,
    world: World,
    artifacts: Any,
    *,
    source: Source,
    entries: list[Entry],
    instruments: tuple[str, ...] | list[str],
    clock: Clock,
    at: dt.datetime | None = None,
) -> tuple[int, int]:
    """Record every headline that names a followed instrument, then the bursts.

    Returns ``(mentions recorded, bursts recorded)``. A headline's event is at
    its own published time and keyed by its title and link, so the same
    headline read on ten wakes is one event; a headline with no published
    time is skipped, because an event without an instant cannot be joined to
    anything. The raw entries are stored once per fetch as an artifact.
    """
    moment = at or clock.now()
    raw = artifacts.put_json(
        session,
        {
            "source": source.name,
            "at": moment.isoformat(),
            "entries": [
                {
                    "title": e.title,
                    "link": e.link,
                    "published": e.published.isoformat() if e.published else None,
                }
                for e in entries
            ],
        },
        kind="news.raw",
        produced_by=source.name,
    )
    world.see(
        session, kind="venue", key=source.name, name=source.name, source=source.url, at=moment
    )
    mentioned: set[str] = set()
    new = 0
    for entry in entries:
        if entry.published is None or entry.published > moment:
            continue
        for symbol in mentions_of(f"{entry.title} {entry.summary}", instruments):
            _, created = world.record(
                session,
                kind="news.mention",
                at=entry.published,
                entity_kind="instrument",
                entity_key=symbol,
                payload={
                    "source": source.name,
                    "title": entry.title[:200],
                    "url": entry.link[:300],
                },
                source=source.url,
                recorded_at=moment,
            )
            new += int(created)
            if created:
                mentioned.add(symbol)

    bursts = 0
    for symbol in sorted(mentioned):
        bursts += int(
            derive_burst(
                session,
                world,
                entity_kind="instrument",
                entity_key=symbol,
                kind_in="news.mention",
                kind_out="news.burst",
                source=source.url,
                moment=moment,
                minimum=BURST_MIN,
                factor=BURST_FACTOR,
                extra={"raw": raw.digest[:16]},
            )
        )
    return new, bursts


@dataclass(frozen=True, slots=True)
class CryptoPanicFeed:
    """CryptoPanic's developer API, read with the token a person supplied.

    Each post names the coins it is about by code; those codes are put in
    the entry's summary as words, so :func:`mentions_of` matches them like
    any headline. The token is read from the environment at fetch time and
    is in the request only.
    """

    source: Source
    timeout: int = 25
    opener: Any = None

    @property
    def name(self) -> str:
        return self.source.name

    def entries(self) -> list[Entry]:
        import json
        import os
        import urllib.parse

        token = os.environ.get(f"{KEY_PREFIX}CRYPTOPANIC_TOKEN", "")
        if not token:
            raise FeedUnavailable(
                f"cryptopanic needs {KEY_PREFIX}CRYPTOPANIC_TOKEN in the service's environment"
            )
        query = urllib.parse.urlencode({"auth_token": token, "public": "true"})
        request = urllib.request.Request(
            f"{self.source.url}?{query}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        fetch = self.opener or urllib.request.urlopen
        try:
            with fetch(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise FeedUnavailable(f"{self.name} refused the request ({error.code})") from error
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise FeedUnavailable(f"{self.name} could not be reached: {error}") from error
        entries: list[Entry] = []
        for post in data.get("results", []) or []:
            codes = [
                str(c.get("code", "")).upper()
                for c in (post.get("instruments") or post.get("currencies") or [])
            ]
            entries.append(
                Entry(
                    title=_strip_tags(str(post.get("title", ""))),
                    link=str(post.get("original_url") or post.get("url") or ""),
                    published=_when(str(post.get("published_at", ""))),
                    summary=("coins: " + " ".join(c for c in codes if c))[:400],
                )
            )
        return [e for e in entries if e.title]
