"""Headlines from free, keyless, official feeds, recorded as events on instruments.

The brief names social posts and news as raw material for the mechanisms the
company should be able to state, and the operator's constraint is that every
source be official and free. What exists on those terms without a credential
is the publishers' own RSS feeds: each is the outlet's official syndication,
public, and rate-limited only by courtesy. They are the catalogue. Nothing
here scrapes a page, and a source that starts to require a key leaves the
catalogue rather than acquiring one.

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
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock
from aurelis.intel.live import USER_AGENT, FeedUnavailable
from aurelis.world.store import World

__all__ = [
    "BURST_FACTOR",
    "BURST_MIN",
    "CATALOGUE",
    "Entry",
    "RssFeed",
    "Source",
    "mentions_of",
    "record_news",
]

BURST_MIN = 3
"""Fewer mentions than this in six hours is never a burst, whatever the rate."""

BURST_FACTOR = Decimal("3")
"""Mentions in the last six hours at or past this multiple of the trailing
week's six-hour rate is ``news.burst``."""

_WINDOW = dt.timedelta(hours=6)
_BASELINE = dt.timedelta(days=7)


@dataclass(frozen=True, slots=True)
class Source:
    """One feed in the catalogue. Everything in it is free and keyless."""

    name: str
    url: str
    covers: str
    kind: str = "rss"
    cost: str = "free"
    key: str = "none"

    def describe(self) -> dict[str, str]:
        return {"covers": self.covers, "kind": self.kind, "cost": self.cost, "key": self.key}


CATALOGUE: dict[str, Source] = {
    "coindesk": Source(
        "coindesk",
        "https://www.coindesk.com/arc/outboundfeeds/rss",
        "CoinDesk headlines: markets, policy, exchanges, across crypto assets",
    ),
    "cointelegraph": Source(
        "cointelegraph",
        "https://cointelegraph.com/rss",
        "Cointelegraph headlines: markets, altcoins, regulation, across crypto assets",
    ),
    "theblock": Source(
        "theblock",
        "https://www.theblock.co/rss.xml",
        "The Block headlines: exchanges, funding, on-chain data, policy",
    ),
    "decrypt": Source(
        "decrypt",
        "https://decrypt.co/feed",
        "Decrypt headlines: crypto, memecoins, culture, policy",
    ),
}
"""Official RSS feeds, no credential, no charge. A source is listed here
only on those terms; the seat shows the agent exactly this."""

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
        recent = World.events_for(
            session,
            entity_kind="instrument",
            entity_key=symbol,
            since=moment - _BASELINE,
            kinds=("news.mention",),
            limit=5000,
        )
        last_six = [e for e in recent if _aware(e.at) > moment - _WINDOW]
        earlier = [e for e in recent if _aware(e.at) <= moment - _WINDOW]
        baseline_hours = Decimal((_BASELINE - _WINDOW).total_seconds()) / Decimal(3600)
        baseline_six = (Decimal(len(earlier)) / baseline_hours * Decimal(6)).quantize(
            Decimal("0.01")
        )
        count = len(last_six)
        if count >= BURST_MIN and Decimal(count) >= BURST_FACTOR * max(
            baseline_six, Decimal("0.5")
        ):
            _, created = world.record(
                session,
                kind="news.burst",
                at=moment,
                entity_kind="instrument",
                entity_key=symbol,
                payload={
                    "mentions_6h": count,
                    "baseline_6h": str(baseline_six),
                    "threshold": (
                        f">= {BURST_MIN} and >= {BURST_FACTOR}x the trailing week's 6h rate"
                    ),
                    "raw": raw.digest[:16],
                },
                source=source.url,
                recorded_at=moment,
            )
            bursts += int(created)
    return new, bursts


def _aware(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
