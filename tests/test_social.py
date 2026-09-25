"""M50 — the company follows Telegram channels and reads Reddit without an app.

* a handle has one canonical spelling, whatever form it was given in, and
  something that is not a handle is refused,
* a follow or a drop is a row, never an edit: the newest decision wins, and a
  drop overrides a token's own link,
* a followed memecoin's own X account and Telegram channel are read off its
  DEX Screener listing and followed while the token is,
* a public channel's preview gives each message's text, time and views, and
  a group, which has no preview, says so,
* Reddit's own feed is read without an app, and a redirect to its login page
  is a failure, not an empty feed,
* the wake reads every followed channel under the news grant, lands a token
  channel's posts on the token and a general channel's on what they name, and
  says how many it read,
* the operator follows, lists and drops from the command line.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
import io
import json
from typing import Any

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from aurelis.cli.main import app
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles, FeedUnavailable
from aurelis.intel.onchain import DexScreenerBoosts, fetch_boosts, record_boosts
from aurelis.intel.social import RedditWeb
from aurelis.intel.telegram import TelegramPublic, parse_preview
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.social.tables import SocialTarget
from aurelis.social.targets import (
    TOKEN_LINK,
    NotAHandle,
    active_targets,
    drop_target,
    follow_target,
    normalise_handle,
)
from aurelis.sources.catalogue import CATALOGUE
from aurelis.sources.seat import request_sources
from aurelis.world.tables import WorldEvent

_HOUR = 3600
_START = 1_780_000_000
_NOW = dt.datetime.fromtimestamp(_START + 200 * _HOUR, tz=dt.UTC)


def _preview(channel: str, messages: list[tuple[int, str, dt.datetime, str]]) -> str:
    parts = []
    for number, text, at, views in messages:
        parts.append(
            f'<div class="tgme_widget_message_wrap js-widget_message_wrap">'
            f'<div class="tgme_widget_message text_not_supported_wrap js-widget_message" '
            f'data-post="{channel}/{number}">'
            f'<div class="tgme_widget_message_bubble">'
            f'<div class="tgme_widget_message_text js-message_text" dir="auto">{text}</div>'
            f'<div class="tgme_widget_message_footer"><div class="tgme_widget_message_info">'
            f'<span class="tgme_widget_message_views">{views}</span>'
            f'<span class="tgme_widget_message_meta"><a class="tgme_widget_message_date" '
            f'href="https://t.me/{channel}/{number}"><time datetime="{at.isoformat()}" '
            f'class="time">12:00</time></a></span></div></div></div></div></div>'
        )
    return f"<html><body><section>{''.join(parts)}</section></body></html>"


_GROUP_PAGE = "<html><body><div class='tgme_page'>Join group</div></body></html>"


def _atom(entries: list[tuple[str, str, dt.datetime]]) -> str:
    items = "".join(
        f"<entry><author><name>/u/someone</name></author>"
        f'<category term="{sub}" label="r/{sub}"/>'
        f'<content type="html">&lt;p&gt;{title} body&lt;/p&gt;</content>'
        f'<id>t3_{i}</id><link href="https://www.reddit.com/r/{sub}/comments/{i}/"/>'
        f"<published>{at.isoformat()}</published><title>{title}</title></entry>"
        for i, (sub, title, at) in enumerate(entries)
    )
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{items}</feed>'


class _Route:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: int = 0) -> Any:  # noqa: ARG002
        self.requests.append(request)
        for prefix, answer in self.routes.items():
            if request.full_url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                if isinstance(answer, str):
                    return _Response(answer.encode(), request.full_url)
                return _Response(json.dumps(answer).encode(), request.full_url)
        raise AssertionError(f"unexpected request {request.full_url}")


class _Response(io.BytesIO):
    def __init__(self, body: bytes, url: str) -> None:
        super().__init__(body)
        self._url = url

    def geturl(self) -> str:
        return self._url


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(_NOW)


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    rows = [[_START + i * _HOUR, 99.0, 101.0, 100.0, 100.0 + i, 5.0] for i in range(201)]

    class _Bars:
        def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
            return io.BytesIO(json.dumps(list(reversed(rows))).encode())

    with built.database.session() as session:
        for symbol in ("BTC-USD", "ETH-USD"):
            built.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Bars(), pause=0),
                desk="crypto",
                symbol=symbol,
                bars=201,
            )
    try:
        yield built
    finally:
        built.close()


# ------------------------------------------------------------ handles


def test_a_handle_has_one_spelling_whatever_form_it_was_given_in() -> None:
    for raw in (
        "whale_alert_io",
        "@Whale_Alert_IO",
        "https://t.me/whale_alert_io",
        "https://t.me/s/whale_alert_io/103434",
        "t.me/whale_alert_io?x=1",
    ):
        assert normalise_handle("telegram", raw) == "whale_alert_io"
    for raw in (
        "WhaleAlert",
        "@whalealert",
        "https://x.com/WhaleAlert/status/1",
        "https://twitter.com/whalealert",
    ):
        assert normalise_handle("x", raw) == "whalealert"
    assert normalise_handle("discord", "https://discord.com/channels/123456/789012") == (
        "123456/789012"
    )
    for platform, raw in (
        ("telegram", "https://t.me/joinchat/AAAA"),
        ("telegram", "ab"),
        ("x", "https://x.com/search?q=btc"),
        ("x", "much_too_long_for_x_handle"),
        ("discord", "general"),
        ("myspace", "tom"),
    ):
        with pytest.raises(NotAHandle):
            normalise_handle(platform, raw)


def test_a_follow_or_drop_is_a_row_the_newest_wins_and_a_drop_overrides_a_token_link(
    company: Runtime, clock: FrozenClock
) -> None:
    with company.database.session() as session:
        follow_target(
            session,
            platform="telegram",
            handle="@Alpha_Calls",
            reason="memecoin calls, early",
            decided_by="operator",
            at=clock.now(),
            ledger=company.ledger,
        )
        clock.advance(minutes=5)
        drop_target(
            session,
            platform="telegram",
            handle="https://t.me/alpha_calls",
            reason="it only reposts what the boosts already show",
            decided_by="operator",
            at=clock.now(),
            ledger=company.ledger,
        )
        clock.advance(minutes=5)
        follow_target(
            session,
            platform="x",
            handle="WhaleAlert",
            reason="large transfers, often early",
            decided_by="operator",
            at=clock.now(),
            ledger=company.ledger,
        )
        rows = active_targets(session)
        kinds = [
            r[0]
            for r in session.execute(
                sa.text("SELECT kind FROM events WHERE kind LIKE 'social.%' ORDER BY seq")
            )
        ]
    assert [(t.platform, t.handle) for t in rows] == [("x", "whalealert")]
    assert kinds == ["social.followed", "social.dropped", "social.followed"]
    engine = company.database.engine
    with pytest.raises(sa.exc.IntegrityError, match="append-only"), engine.begin() as c:
        c.execute(sa.update(SocialTarget).values(reason="rewritten afterwards, silently"))
    with pytest.raises(sa.exc.IntegrityError, match="append-only"), engine.begin() as c:
        c.execute(sa.delete(SocialTarget))


def _boosted(company: Runtime, links: list[dict[str, str]]) -> str:
    feed = DexScreenerBoosts(
        CATALOGUE["dexscreener_boosts"],
        opener=_Route(
            {
                "https://api.dexscreener.com/token-boosts/latest/v1": [
                    {
                        "url": "https://dexscreener.com/solana/AAA",
                        "chainId": "solana",
                        "tokenAddress": "AAA",
                        "totalAmount": "10",
                        "amount": "10",
                        "links": links,
                    }
                ],
                "https://api.dexscreener.com/token-boosts/top/v1": [],
                "https://api.dexscreener.com/tokens/v1/solana/": [
                    {
                        "chainId": "solana",
                        "dexId": "raydium",
                        "pairAddress": "pair-AAA",
                        "baseToken": {"address": "AAA", "name": "Moon coin", "symbol": "MOON"},
                        "priceUsd": "0.0012",
                        "liquidity": {"usd": 90_000},
                        "marketCap": 1_200_000,
                        "volume": {"h24": 350_000},
                        "priceChange": {"h24": 42.5},
                    }
                ],
            }
        ),
    )
    with company.database.session() as session:
        record_boosts(
            session,
            company.world,
            company.artifacts,
            source=CATALOGUE["dexscreener_boosts"],
            fetched=fetch_boosts(feed),
            clock=company.clock,
        )
    return "solana:AAA"


def test_a_followed_tokens_own_x_and_telegram_are_followed_while_the_token_is(
    company: Runtime, clock: FrozenClock
) -> None:
    token = _boosted(
        company,
        [
            {"type": "twitter", "url": "https://x.com/MoonCoinSol"},
            {"type": "telegram", "url": "https://t.me/mooncoin_portal"},
            {"label": "Website", "url": "https://moon.example"},
        ],
    )
    with company.database.session() as session:
        followed = active_targets(session, tokens=(token,))
        unfollowed = active_targets(session, tokens=())
        drop_target(
            session,
            platform="telegram",
            handle="mooncoin_portal",
            reason="a shill channel: every message is a buy call",
            decided_by="operator",
            at=clock.now(),
        )
        after_drop = active_targets(session, tokens=(token,))
    assert {(t.platform, t.handle, t.on, t.origin) for t in followed} == {
        ("telegram", "mooncoin_portal", token, TOKEN_LINK),
        ("x", "mooncoinsol", token, TOKEN_LINK),
    }
    assert unfollowed == [], "a token no longer followed brings no channels"
    assert [(t.platform, t.handle) for t in after_drop] == [("x", "mooncoinsol")]


def test_a_cashtag_names_its_coin_and_a_token_is_named_only_by_its_cashtag() -> None:
    from aurelis.intel.news import mentions_of

    instruments = ("BTC-USD", "ONE-USD", "solana:AAA")
    names = {"solana:AAA": "MOON"}

    def named(text: str) -> list[str]:
        return mentions_of(text, instruments, names)

    assert named("2,699 $BTC moved to Binance") == ["BTC-USD"], "the bug M50 found"
    assert named("$btc and bitcoin") == ["BTC-USD"]
    assert named("$ONE rallies") == ["ONE-USD"] and named("one day soon") == []
    assert named("$MOON is sending it") == ["solana:AAA"]
    assert named("to the MOON we go") == [], "a token's bare ticker is a word"
    assert named("US$5 fee, $BTCX") == []
    assert mentions_of("$MOON", instruments) == [], "a token nobody has named is not matched"


# ------------------------------------------------------------ readers


def test_a_public_channels_preview_gives_text_time_and_views_and_a_group_says_it_has_none() -> None:
    at = _NOW - dt.timedelta(hours=1)
    html = _preview(
        "whale_alert_io",
        [
            (7, "2,699 <b>$BTC</b> transferred<br/>to #Binance", at, "7.06K"),
            (8, "250,000,000 $USDC minted", at + dt.timedelta(minutes=5), "1.2M"),
        ],
    )
    posts = parse_preview(html, "whale_alert_io")
    assert [p.id for p in posts] == ["telegram:whale_alert_io/7", "telegram:whale_alert_io/8"]
    assert posts[0].text == "2,699 $BTC transferred to #Binance"
    assert posts[0].at == at and posts[0].likes == 7060 and posts[1].likes == 1_200_000
    assert posts[0].url == "https://t.me/whale_alert_io/7"
    feed = TelegramPublic(
        CATALOGUE["telegram_channels"],
        opener=_Route({"https://t.me/s/some_group": _GROUP_PAGE}),
    )
    with pytest.raises(FeedUnavailable, match="no public preview"):
        feed.posts("some_group")


def test_reddit_is_read_from_its_own_feed_and_a_login_redirect_is_a_failure() -> None:
    at = _NOW - dt.timedelta(hours=2)
    url = CATALOGUE["reddit_web_memecoins"].url
    feed = RedditWeb(
        CATALOGUE["reddit_web_memecoins"],
        opener=_Route({url: _atom([("memecoins", "MOON is sending it", at)])}),
    )
    (post,) = feed.posts()
    assert post.text == "MOON is sending it MOON is sending it body"
    assert post.venue == "memecoins" and post.author == "someone" and post.at == at

    class _Login:
        def __call__(self, request: Any, timeout: int = 0) -> Any:  # noqa: ARG002
            return _Response(b"<html>login</html>", "https://www.reddit.com/login/?dest=x")

    with pytest.raises(FeedUnavailable, match="login page"):
        RedditWeb(CATALOGUE["reddit_web_memecoins"], opener=_Login()).posts()


# ------------------------------------------------------------ the wake


class _Direct:
    def __init__(self, text: str) -> None:
        self._text = text
        self.name = "mock"

    def complete(self, session: Any, request: LlmRequest) -> Any:  # noqa: ARG002
        return MockProvider(responder=lambda _r: self._text).complete(request)


def test_the_wake_reads_every_followed_channel_and_lands_posts_where_they_belong(
    company: Runtime, clock: FrozenClock
) -> None:
    with company.database.session() as session:
        company.grants.grant(
            session,
            source="news",
            desk="crypto",
            instruments=("BTC-USD", "ETH-USD"),
            granted_by="test",
            reason="a test grant, so the service has something to read",
        )
        request_sources(
            _Direct(
                "SOURCES: telegram_channels, reddit_web_crypto\n"
                "BECAUSE: whale alerts and the crowd, where attention forms first.\n"
            ),
            session,
            agent_ref=company.roster.by_handle(session, "INTEL").ref,
            instruments=("BTC-USD", "ETH-USD"),
            ledger=company.ledger,
            clock=clock,
        )
        follow_target(
            session,
            platform="telegram",
            handle="whale_alert_io",
            reason="large transfers, often before exchange flows",
            decided_by="operator",
            at=clock.now(),
        )
        follow_target(
            session,
            platform="telegram",
            handle="eth_only_news",
            on="ETH-USD",
            reason="an Ethereum-only channel: every post is about ETH",
            decided_by="operator",
            at=clock.now(),
        )
        follow_target(
            session,
            platform="telegram",
            handle="gone_private",
            reason="was public last month",
            decided_by="operator",
            at=clock.now(),
        )
    at = _NOW - dt.timedelta(minutes=30)
    feeds: dict[str, Any] = {
        "telegram_channels": TelegramPublic(
            CATALOGUE["telegram_channels"],
            opener=_Route(
                {
                    "https://t.me/s/whale_alert_io": _preview(
                        "whale_alert_io", [(1, "2,699 $BTC moved to Binance", at, "5K")]
                    ),
                    "https://t.me/s/eth_only_news": _preview(
                        "eth_only_news", [(9, "gas is low today", at, "300")]
                    ),
                    "https://t.me/s/gone_private": _GROUP_PAGE,
                }
            ),
        ),
        "reddit_web_crypto": RedditWeb(
            CATALOGUE["reddit_web_crypto"],
            opener=_Route(
                {
                    CATALOGUE["reddit_web_crypto"].url: _atom(
                        [("Bitcoin", "Bitcoin to the moon", at)]
                    )
                }
            ),
        ),
    }
    service = Service(company, news=lambda name: feeds[name], cycles_per_wake=1, calls_per_day=0)
    wake = cycle_once(company, service=service)
    with company.database.session() as session:
        posts = session.execute(
            sa.select(WorldEvent.entity_key, WorldEvent.payload).where(
                WorldEvent.kind == "social.post"
            )
        ).all()
    landed = sorted((key, payload["source"], payload["text"][:12]) for key, payload in posts)
    assert landed == [
        ("BTC-USD", "reddit_web_crypto", "Bitcoin to t"),
        ("BTC-USD", "telegram_channels", "2,699 $BTC m"),
        ("ETH-USD", "telegram_channels", "gas is low t"),
    ]
    assert "telegram_channels: 2 of 3 followed channel(s) read" in wake.note, wake.note
    assert "gone_private" in wake.note, "the channel that could not be read is named"


# ------------------------------------------------------------ the operator


def test_the_operator_follows_lists_and_drops_from_the_command_line(settings: Settings) -> None:
    runner = CliRunner()
    home = ["-w", str(settings.home)]
    followed = runner.invoke(
        app,
        [
            "social",
            "follow",
            "telegram",
            "https://t.me/whale_alert_io",
            "--reason",
            "large transfers, often early",
            *home,
        ],
    )
    assert followed.exit_code == 0, followed.output
    assert "following telegram:whale_alert_io" in followed.output
    refused = runner.invoke(
        app, ["social", "follow", "telegram", "joinchat", "--reason", "not a channel", *home]
    )
    assert refused.exit_code == 1 and "not a public Telegram channel" in refused.output
    listed = runner.invoke(app, ["social", "list", *home], env={"COLUMNS": "200"})
    assert listed.exit_code == 0 and "whale_alert_io" in listed.output, listed.output
    dropped = runner.invoke(
        app,
        ["social", "drop", "telegram", "whale_alert_io", "--reason", "too noisy to use", *home],
    )
    assert dropped.exit_code == 0 and "dropped telegram:whale_alert_io" in dropped.output
