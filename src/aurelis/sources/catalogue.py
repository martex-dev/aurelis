"""The catalogue of sources the company could read, for every market.

Three constraints, unchanged since M41: the agents decide what they need;
every source is free; the company fetches nothing a person did not grant.
M43 widens the first two without touching the third. *Free* no longer means
*keyless*: a source may need a credential that its vendor issues at no
charge, and a person supplies it in the service's environment. The agents
are shown such a source with its key status, may ask for it, and the wake
says which key is missing until it is there. Nothing here reads a key's
value into the record; the catalogue knows only whether one is set.

Every source is the vendor's own, official interface: a publisher's RSS
feed, an exchange's or an aggregator's public JSON API, a platform's
documented read endpoint. Nothing scrapes a page. A source that starts to
require payment leaves the catalogue.

What is *not* here, and why, so nobody looks for it:

* **X / Twitter** — the free tier of the official API cannot read posts.
* **Telegram channels** — the Bot API sees only channels the bot is added
  to, and reading a public channel any other way means logging in as a
  person, which is that person's account, not the company's.
* **GDELT** — throttled the first request at M41.

Which sources the company reads is not decided here: an agent from Market
Intelligence is shown this catalogue and the instruments the company
follows on each desk, and asks (:mod:`aurelis.sources.seat`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "CATALOGUE",
    "KEY_PREFIX",
    "KINDS",
    "Source",
    "available",
    "key_status",
    "markets_of",
]

KEY_PREFIX = "AURELIS_KEY_"
"""Every credential a person supplies is an environment variable with this
prefix. The name is on the record; the value never is."""

KINDS: tuple[str, ...] = (
    "rss",
    "stocktwits",
    "bluesky",
    "reddit",
    "cryptopanic",
    "dexscreener",
    "geckoterminal",
)
"""How a source is read. Each kind has one reader in
:mod:`aurelis.intel.news`, :mod:`aurelis.intel.social` or
:mod:`aurelis.intel.onchain`, built by :func:`aurelis.service.grants.news_for`."""


@dataclass(frozen=True, slots=True)
class Source:
    """One source in the catalogue."""

    name: str
    url: str
    covers: str
    kind: str = "rss"
    cost: str = "free"
    markets: tuple[str, ...] = ("crypto",)
    """Which desks it bears on, by desk name."""

    keys: tuple[str, ...] = ()
    """Environment variables a person must set before it can be read.
    Empty for a keyless source."""

    @property
    def keyless(self) -> bool:
        return not self.keys

    @property
    def available(self) -> bool:
        """Whether every key it needs is set. A keyless source always is."""
        return all(os.environ.get(k) for k in self.keys)

    @property
    def missing_keys(self) -> tuple[str, ...]:
        return tuple(k for k in self.keys if not os.environ.get(k))

    @property
    def key(self) -> str:
        """The key status in words, for the seat, the CLI and the station."""
        if not self.keys:
            return "none"
        if self.available:
            return "supplied by a person"
        return f"needs {', '.join(self.missing_keys)} from a person; not supplied"

    def describe(self) -> dict[str, str]:
        return {
            "covers": self.covers,
            "kind": self.kind,
            "cost": self.cost,
            "key": self.key,
            "markets": ", ".join(self.markets),
        }


_CRYPTO = ("crypto", "memecoin")
_MACRO = ("equities", "fx", "futures", "commodities", "options")

CATALOGUE: dict[str, Source] = {
    source.name: source
    for source in (
        # -- headlines, crypto ------------------------------------------------
        Source(
            "coindesk",
            "https://www.coindesk.com/arc/outboundfeeds/rss",
            "CoinDesk headlines: markets, policy, exchanges, across crypto assets",
            markets=_CRYPTO,
        ),
        Source(
            "cointelegraph",
            "https://cointelegraph.com/rss",
            "Cointelegraph headlines: markets, altcoins, regulation, across crypto assets",
            markets=_CRYPTO,
        ),
        Source(
            "theblock",
            "https://www.theblock.co/rss.xml",
            "The Block headlines: exchanges, funding, on-chain data, policy",
            markets=_CRYPTO,
        ),
        Source(
            "decrypt",
            "https://decrypt.co/feed",
            "Decrypt headlines: crypto, memecoins, culture, policy",
            markets=_CRYPTO,
        ),
        Source(
            "cryptopanic",
            "https://cryptopanic.com/api/developer/v2/posts/",
            "CryptoPanic: aggregated crypto news and posts, tagged with the coins they "
            "name; the developer plan is free and needs a token",
            kind="cryptopanic",
            markets=_CRYPTO,
            keys=(f"{KEY_PREFIX}CRYPTOPANIC_TOKEN",),
        ),
        # -- social, per followed instrument ---------------------------------
        Source(
            "stocktwits",
            "https://api.stocktwits.com/api/2/streams/symbol/",
            "Stocktwits: the public message stream of each followed symbol, with the "
            "poster's own bullish/bearish tag; crypto and equities",
            kind="stocktwits",
            markets=("crypto", "memecoin", "equities"),
        ),
        Source(
            "bluesky",
            "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
            "Bluesky: the newest public posts naming each followed instrument by its "
            "cashtag or name, with like and repost counts",
            kind="bluesky",
            markets=("crypto", "memecoin", "equities"),
        ),
        Source(
            "reddit_crypto",
            "https://oauth.reddit.com/r/CryptoCurrency+CryptoMarkets/new",
            "Reddit r/CryptoCurrency and r/CryptoMarkets: new posts; the official API "
            "is free and needs an app's client id and secret",
            kind="reddit",
            markets=("crypto",),
            keys=(f"{KEY_PREFIX}REDDIT_CLIENT_ID", f"{KEY_PREFIX}REDDIT_CLIENT_SECRET"),
        ),
        Source(
            "reddit_memecoins",
            "https://oauth.reddit.com/r/memecoins+solana+SatoshiStreetBets/new",
            "Reddit r/memecoins, r/solana and r/SatoshiStreetBets: new posts, where "
            "memecoin attention forms; the official API is free and needs an app's "
            "client id and secret",
            kind="reddit",
            markets=("memecoin",),
            keys=(f"{KEY_PREFIX}REDDIT_CLIENT_ID", f"{KEY_PREFIX}REDDIT_CLIENT_SECRET"),
        ),
        Source(
            "reddit_stocks",
            "https://oauth.reddit.com/r/stocks+wallstreetbets/new",
            "Reddit r/stocks and r/wallstreetbets: new posts; the official API is "
            "free and needs an app's client id and secret",
            kind="reddit",
            markets=("equities", "options"),
            keys=(f"{KEY_PREFIX}REDDIT_CLIENT_ID", f"{KEY_PREFIX}REDDIT_CLIENT_SECRET"),
        ),
        # -- on-chain attention, memecoins --------------------------------------
        Source(
            "dexscreener_boosts",
            "https://api.dexscreener.com/token-boosts/latest/v1",
            "DEX Screener: tokens whose promoters just paid to boost them, and the "
            "most-boosted, with each token's symbol, liquidity and market cap; where "
            "a memecoin's paid attention shows first",
            kind="dexscreener",
            markets=("memecoin",),
        ),
        Source(
            "geckoterminal_trending",
            "https://api.geckoterminal.com/api/v2/networks/{network}/trending_pools",
            "GeckoTerminal: the pools trending on Solana, Base, Ethereum and BNB "
            "Chain, with volume, price change and liquidity; a token entering the "
            "trending list is an event",
            kind="geckoterminal",
            markets=("memecoin",),
        ),
        # -- headlines, other markets --------------------------------------------
        Source(
            "sec_press",
            "https://www.sec.gov/news/pressreleases.rss",
            "SEC press releases: enforcement, rules, listings and delistings",
            markets=("equities", "options", "crypto"),
        ),
        Source(
            "fed_press",
            "https://www.federalreserve.gov/feeds/press_all.xml",
            "Federal Reserve press releases: rate decisions, statements, speeches",
            markets=_MACRO,
        ),
        Source(
            "boe_news",
            "https://www.bankofengland.co.uk/rss/news",
            "Bank of England news: rate decisions, statements, speeches",
            markets=("fx", "futures"),
        ),
        Source(
            "eia_today",
            "https://www.eia.gov/rss/todayinenergy.xml",
            "EIA Today in Energy: oil, gas and power supply, inventories, prices",
            markets=("commodities", "futures"),
        ),
        Source(
            "cnbc_markets",
            "https://www.cnbc.com/id/10000664/device/rss/rss.html",
            "CNBC markets headlines: equities, indices, earnings, macro",
            markets=_MACRO,
        ),
        Source(
            "marketwatch_top",
            "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            "MarketWatch top stories: equities, macro, commodities",
            markets=_MACRO,
        ),
        Source(
            "yahoo_finance",
            "https://finance.yahoo.com/news/rssindex",
            "Yahoo Finance headlines: equities, earnings, macro, crypto",
            markets=("equities", "options", "crypto"),
        ),
        Source(
            "oilprice",
            "https://oilprice.com/rss/main",
            "OilPrice headlines: crude, gas, OPEC, energy markets",
            markets=("commodities", "futures"),
        ),
        Source(
            "fxstreet",
            "https://www.fxstreet.com/rss/news",
            "FXStreet news: currencies, central banks, macro releases",
            markets=("fx", "futures"),
        ),
    )
}
"""Every source the agents may ask for. Free, official, and either keyless
or keyed by a person. A source enters by a code change, which is a person's
decision on the record; the digest of the names is what an agent answered on."""


def markets_of(catalogue: dict[str, Source] | None = None) -> tuple[str, ...]:
    seen: list[str] = []
    for source in (catalogue or CATALOGUE).values():
        for market in source.markets:
            if market not in seen:
                seen.append(market)
    return tuple(seen)


def available(name: str, catalogue: dict[str, Source] | None = None) -> bool:
    source = (catalogue or CATALOGUE).get(name)
    return source is not None and source.available


def key_status(catalogue: dict[str, Source] | None = None) -> list[dict[str, str]]:
    """Every keyed source, which variables it needs, and whether each is set.

    Names only. The value of a key is never read here, printed anywhere, or
    written to the record.
    """
    rows: list[dict[str, str]] = []
    for source in (catalogue or CATALOGUE).values():
        for variable in source.keys:
            rows.append(
                {
                    "source": source.name,
                    "variable": variable,
                    "set": "yes" if os.environ.get(variable) else "no",
                }
            )
    return rows
