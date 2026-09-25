"""M51 — X and Discord through Aurelis's own browser profile, read-only.

* X's timeline JSON gives each post once, with its author, time, text (the
  long form when there is one), likes and reposts, whatever shape surrounds it,
* Discord's channel JSON gives each message once, with embeds as text and
  reactions counted,
* a cashtag is a live search and anything else an account, and a reader opens
  only URLs built from a validated handle,
* nothing is read until a person has signed in once, and the wake says so,
* once signed in, the wake reads the followed accounts and a rotating slice of
  cashtag searches, lands a token's posts on the token, and stops reading a
  platform the moment the profile is sent to a sign-in page.

**Nothing here touches the network or opens a browser.**
"""

from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.browser import SIGNED_IN_MARK, browser_ready, profile_home
from aurelis.intel.live import CoinbaseCandles, FeedUnavailable
from aurelis.intel.xdiscord import DiscordBrowser, XBrowser, _x_url, discord_posts, x_posts
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.social.targets import NotAHandle, follow_target
from aurelis.sources import reading
from aurelis.sources.catalogue import CATALOGUE
from aurelis.sources.seat import request_sources
from aurelis.world.tables import WorldEvent

_HOUR = 3600
_START = 1_780_000_000
_NOW = dt.datetime.fromtimestamp(_START + 200 * _HOUR, tz=dt.UTC)


def _x_time(at: dt.datetime) -> str:
    return at.strftime("%a %b %d %H:%M:%S +0000 %Y")


def _tweet(tweet_id: str, text: str, at: dt.datetime, *, user: str, new_shape: bool) -> Any:
    user_result = (
        {"core": {"screen_name": user}, "legacy": {}}
        if new_shape
        else {"legacy": {"screen_name": user}}
    )
    return {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": tweet_id,
                        "core": {"user_results": {"result": user_result}},
                        "legacy": {
                            "id_str": tweet_id,
                            "full_text": text,
                            "created_at": _x_time(at),
                            "favorite_count": 12,
                            "retweet_count": 3,
                        },
                    }
                }
            }
        }
    }


def _timeline(*entries: Any) -> Any:
    return {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [{"type": "TimelineAddEntries", "entries": list(entries)}]
                    }
                }
            }
        }
    }


# ------------------------------------------------------------ parsers


def test_x_timeline_json_gives_each_post_once_with_author_time_text_and_counts() -> None:
    at = _NOW - dt.timedelta(minutes=20)
    long_tweet = _tweet(
        "2", "short form…", at - dt.timedelta(minutes=5), user="Dev", new_shape=True
    )
    long_tweet["content"]["itemContent"]["tweet_results"]["result"]["note_tweet"] = {
        "note_tweet_results": {"result": {"text": "the whole long form of $MOON thread"}}
    }
    bodies = [
        _timeline(
            _tweet("1", "$MOON sending it", at, user="MoonCoinSol", new_shape=False), long_tweet
        ),
        _timeline(_tweet("1", "$MOON sending it", at, user="MoonCoinSol", new_shape=False)),
    ]
    posts = x_posts(bodies, venue="x/$MOON")
    assert [p.id for p in posts] == ["x:1", "x:2"], "once each, newest first"
    assert posts[0].author == "MoonCoinSol" and posts[0].at == at.replace(microsecond=0)
    assert posts[0].likes == 12 and posts[0].reposts == 3
    assert posts[0].url == "https://x.com/MoonCoinSol/status/1"
    assert posts[1].text == "the whole long form of $MOON thread" and posts[1].author == "Dev"


def test_discord_channel_json_gives_each_message_once_with_embeds_and_reactions() -> None:
    at = _NOW - dt.timedelta(minutes=3)
    messages = [
        {
            "id": "901",
            "content": "$MOON call: entry now",
            "timestamp": at.isoformat(),
            "author": {"username": "caller"},
            "reactions": [{"count": 4}, {"count": 2}],
        },
        {
            "id": "902",
            "content": "",
            "timestamp": at.isoformat(),
            "author": {"username": "bot"},
            "embeds": [{"title": "New listing", "description": "$CAT on raydium"}],
        },
        {"id": "903", "content": "", "timestamp": at.isoformat(), "author": {}},
    ]
    posts = discord_posts([messages, messages], channel="111111/222222")
    assert [p.id for p in posts] == ["discord:901", "discord:902"]
    assert posts[0].likes == 6 and posts[0].at == at and posts[0].author == "caller"
    assert posts[1].text == "New listing $CAT on raydium"
    assert posts[0].url == "https://discord.com/channels/111111/222222/901"


def test_a_cashtag_is_a_live_search_and_anything_else_a_validated_account() -> None:
    assert _x_url("$MOON") == (
        "https://x.com/search?q=%24MOON&src=typed_query&f=live",
        "SearchTimeline",
    )
    assert _x_url("@WhaleAlert") == ("https://x.com/whalealert", "UserTweets")
    with pytest.raises(NotAHandle):
        _x_url("https://evil.example/phish")


class _Profile:
    """A stand-in for the open profile: answers by URL, records what it opened."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.opened: list[str] = []

    def capture(self, url: str, wanted: Any, **_: Any) -> list[Any]:
        self.opened.append(url)
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return [answer]
        return []


def test_a_reader_opens_only_the_url_it_built_and_says_when_a_page_loaded_nothing() -> None:
    profile = _Profile({})  # the page loaded, and no messages call came back
    reader = DiscordBrowser(CATALOGUE["discord_browser"], opener=profile)
    with pytest.raises(FeedUnavailable, match="member of the server"):
        reader.posts("https://discord.com/channels/111111/222222")
    assert profile.opened == ["https://discord.com/channels/111111/222222"]
    with pytest.raises(NotAHandle):
        reader.posts("https://discord.gg/invite-code")


# ------------------------------------------------------------ the wake


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
        built.grants.grant(
            session,
            source="news",
            desk="crypto",
            instruments=("BTC-USD", "ETH-USD"),
            granted_by="test",
            reason="a test grant, so the service has something to read",
        )
    try:
        yield built
    finally:
        built.close()


class _Direct:
    def __init__(self, text: str) -> None:
        self._text = text
        self.name = "mock"

    def complete(self, session: Any, request: LlmRequest) -> Any:  # noqa: ARG002
        return MockProvider(responder=lambda _r: self._text).complete(request)


def _ask_for_x(company: Runtime, clock: FrozenClock) -> None:
    with company.database.session() as session:
        request_sources(
            _Direct("SOURCES: x_browser\nBECAUSE: where memecoin attention forms first.\n"),
            session,
            agent_ref=company.roster.by_handle(session, "INTEL").ref,
            instruments=("BTC-USD", "ETH-USD"),
            ledger=company.ledger,
            clock=clock,
        )
        follow_target(
            session,
            platform="x",
            handle="WhaleAlert",
            on="BTC-USD",
            reason="large transfers, often early",
            decided_by="operator",
            at=clock.now(),
        )


def _sign_in(workspace: Path, *platforms: str) -> None:
    home = profile_home(workspace)
    home.mkdir(parents=True, exist_ok=True)
    (home / SIGNED_IN_MARK).write_text(json.dumps({"platforms": list(platforms)}))


def test_nothing_is_read_until_a_person_signs_in_once_and_the_wake_says_so(
    company: Runtime, clock: FrozenClock
) -> None:
    _ask_for_x(company, clock)
    profile = _Profile({})
    reader = XBrowser(CATALOGUE["x_browser"], opener=profile)
    service = Service(company, news=lambda name: reader, cycles_per_wake=1, calls_per_day=0)
    assert not browser_ready("x", company.settings.workspace)
    wake = cycle_once(company, service=service)
    assert "x_browser: not read, needs a person to sign into x once" in wake.note
    assert profile.opened == [], "no page is opened before the sign-in"


def test_once_signed_in_the_wake_reads_accounts_and_cashtags_and_stops_at_a_sign_in_page(
    company: Runtime, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ask_for_x(company, clock)
    _sign_in(company.settings.workspace, "x")
    at = _NOW - dt.timedelta(minutes=10)
    profile = _Profile(
        {
            "https://x.com/whalealert": _timeline(
                _tweet(
                    "10", "2,699 BTC moved to an exchange", at, user="whale_alert", new_shape=True
                )
            ),
            "https://x.com/search?q=%24BTC": _timeline(
                _tweet("11", "$BTC looks heavy", at, user="trader", new_shape=True)
            ),
            "https://x.com/search?q=%24ETH": _timeline(
                _tweet("12", "$ETH gas is low", at, user="dev", new_shape=True)
            ),
        }
    )
    reader = XBrowser(CATALOGUE["x_browser"], opener=profile)
    service = Service(company, news=lambda name: reader, cycles_per_wake=1, calls_per_day=0)
    wake = cycle_once(company, service=service)
    with company.database.session() as session:
        landed = sorted(
            (key, payload["id"])
            for key, payload in session.execute(
                sa.select(WorldEvent.entity_key, WorldEvent.payload).where(
                    WorldEvent.kind == "social.post"
                )
            ).all()
        )
    assert landed == [("BTC-USD", "x:10"), ("BTC-USD", "x:11"), ("ETH-USD", "x:12")]
    assert "x_browser: 3 read, 0 not" in wake.note, wake.note

    # A slice, rotating: one search a wake reads the next instrument in turn.
    monkeypatch.setattr(reading, "X_SEARCHES_PER_WAKE", 1)
    asked = [[a for a, _ in _asks(reader, rotation=r)] for r in (0, 1, 2)]
    assert asked == [["whalealert", "$BTC"], ["whalealert", "$ETH"], ["whalealert", "$BTC"]]

    # Sent to a sign-in page: the platform stops for this wake, one failure named.
    signed_out = _Profile(
        {"https://x.com/": FeedUnavailable("x sent the profile to a sign-in page; run login")}
    )
    with pytest.raises(FeedUnavailable, match="read nothing"):
        reading.fetch_source(
            CATALOGUE["x_browser"],
            XBrowser(CATALOGUE["x_browser"], opener=signed_out),
            ("BTC-USD", "ETH-USD"),
            targets=_targets(company),
        )
    assert len(signed_out.opened) == 1, "stopped at the first sign-in page"


def _targets(company: Runtime) -> list[Any]:
    from aurelis.social.targets import active_targets

    with company.database.session() as session:
        return active_targets(session)


def _asks(reader: XBrowser, *, rotation: int) -> list[tuple[str, str | None]]:
    seen: list[tuple[str, str | None]] = []

    class _Spy:
        name = reader.name

        def posts(self, ask: str) -> list[Any]:
            seen.append((ask, None))
            return []

        def close(self) -> None:
            return None

    from aurelis.social.targets import Target

    reading.fetch_source(
        CATALOGUE["x_browser"],
        _Spy(),
        ("BTC-USD", "ETH-USD"),
        targets=[Target("x", "whalealert", "BTC-USD", "operator", "a test follow")],
        rotation=rotation,
    )
    return seen
