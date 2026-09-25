"""M54 — the company chooses whom it follows by each voice's lead over price.

The acceptance criteria, each with a test named after it:

* a voice whose posts come before its instrument beats its peers leads price,
  and one whose posts come after the move trails it,
* a move inside the bar a post was made in is never credited as a lead,
* a voice's posts within a day are one episode, and a record is read only
  from ten,
* the bar a lead must clear is divided by the number of voices measured,
* an episode whose day has not been recorded yet is pending, not a miss,
* only what was recorded by the moment measured is read,
* a post from a platform with no handle to follow is not a voice,
* an agent follows and drops from what the record offers, with its reason and
  the record on each row, and the sitting cites the record it was shown,
* a reply that names a voice it was not offered is refused, recorded, and
  changes nothing,
* with nothing eligible, nobody is asked and no model call is made,
* the wake curates at most once a day under the news grant, and says so,
* the station shows every voice's record and every sitting.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.canonical import sha256_of
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.snapshots import MarketSnapshot, SnapshotBar
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.social.curation import curate, curation_due, followed_targets
from aurelis.social.tables import SocialTarget
from aurelis.social.targets import active_targets, follow_target
from aurelis.social.voices import MIN_EPISODES, measure_voices, sign_test, voice_of

_T0 = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
_NOW = _T0 + dt.timedelta(days=30)
_HOURS = 30 * 24
_STEP = Decimal("1.02")

LEADER = [_T0 + dt.timedelta(days=2 + 2 * k, hours=10, minutes=30) for k in range(12)]
"""x/leader posts about LEAD-USD; LEAD-USD steps up in the next bar."""

CHASER = [_T0 + dt.timedelta(days=2 + 2 * k, hours=22, minutes=30) for k in range(12)]
"""x/chaser posts about CHASE-USD three hours after it stepped up."""

SAMEBAR = [_T0 + dt.timedelta(days=3 + 2 * k, hours=16, minutes=30) for k in range(11)]
"""x/samebar posts about SAME-USD in the bar it stepped up in."""

QUIET = [_T0 + dt.timedelta(days=3 + 2 * k, hours=4, minutes=30) for k in range(11)]
"""telegram/quietcalls posts about QUIET-USD, which never moves."""


def _floor(moment: dt.datetime) -> dt.datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _steps(at: dt.datetime, when: list[dt.datetime]) -> int:
    return sum(1 for moment in when if moment <= at)


PRICES: dict[str, Callable[[dt.datetime], Decimal]] = {
    # The bar opening after the post is the first to carry the step.
    "LEAD-USD": lambda ts: 100 * _STEP ** _steps(ts, [m + dt.timedelta(hours=1) for m in LEADER]),
    # Three hours before the post.
    "CHASE-USD": lambda ts: 100 * _STEP ** _steps(ts, [m - dt.timedelta(hours=3) for m in CHASER]),
    # The bar the post falls inside carries the step.
    "SAME-USD": lambda ts: 100 * _STEP ** _steps(ts, [_floor(m) for m in SAMEBAR]),
    "QUIET-USD": lambda ts: Decimal(100),
    "FLAT-USD": lambda ts: Decimal(50),
}


def _record_prices(company: Runtime, *, fetched_at: dt.datetime = _NOW) -> None:
    with company.database.session() as session:
        for symbol, price in PRICES.items():
            ref = allocate_ref(session, RefKind.SNAPSHOT)
            stamps = [_T0 + dt.timedelta(hours=h) for h in range(_HOURS)]
            session.add(
                MarketSnapshot(
                    snapshot_id=uuid7(),
                    ref=ref,
                    desk="crypto",
                    source="fixture",
                    endpoint="fixture",
                    symbol=symbol,
                    interval="1h",
                    bars=len(stamps),
                    first_at=stamps[0],
                    last_at=stamps[-1],
                    digest=sha256_of({"symbol": symbol}),
                    is_live=False,
                    fetched_at=fetched_at,
                )
            )
            for ts in stamps:
                close = str(price(ts))
                session.add(
                    SnapshotBar(
                        snapshot_ref=ref,
                        timestamp=ts,
                        open=close,
                        high=close,
                        low=close,
                        close=close,
                        volume="1",
                    )
                )
            session.flush()


def _post(
    company: Runtime,
    *,
    at: dt.datetime,
    instrument: str,
    venue: str,
    author: str,
    text: str = "a post",
) -> None:
    with company.database.session() as session:
        company.world.record(
            session,
            kind="social.post",
            at=at,
            entity_kind="instrument",
            entity_key=instrument,
            payload={
                "source": "fixture",
                "id": f"{venue}:{at.isoformat()}:{instrument}",
                "author": author,
                "text": text,
                "venue": venue,
            },
            source="fixture",
            recorded_at=at + dt.timedelta(minutes=20),
        )


def _voices(company: Runtime) -> None:
    for moment in LEADER:
        _post(company, at=moment, instrument="LEAD-USD", venue="x/$LEAD", author="Leader")
    for moment in CHASER:
        _post(company, at=moment, instrument="CHASE-USD", venue="x/$CHASE", author="Chaser")
    for moment in SAMEBAR:
        _post(company, at=moment, instrument="SAME-USD", venue="x/$SAME", author="SameBar")
    for moment in QUIET:
        _post(
            company,
            at=moment,
            instrument="QUIET-USD",
            venue="telegram/quietcalls",
            author="quietcalls",
        )
    burst = _T0 + dt.timedelta(days=20, hours=9)
    for n, symbol in enumerate(("FLAT-USD", "QUIET-USD", "LEAD-USD")):
        _post(
            company,
            at=burst + dt.timedelta(minutes=10 * n),
            instrument=symbol,
            venue="x/$FLAT",
            author="newbie",
        )
    _post(
        company,
        at=_T0 + dt.timedelta(days=5),
        instrument="LEAD-USD",
        venue="cryptocurrency",
        author="someone",
    )


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(_NOW)


def _company(settings: Settings, clock: FrozenClock, responder: Any) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=responder))
    built.initialise()
    built.staff()
    return built


def _seeded(settings: Settings, clock: FrozenClock, responder: Any) -> Runtime:
    built = _company(settings, clock, responder)
    _record_prices(built)
    _voices(built)
    with built.database.session() as session:
        follow_target(
            session,
            platform="telegram",
            handle="quietcalls",
            reason="the operator thought it early on memecoins",
            decided_by="operator",
            at=_T0,
        )
    return built


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Iterator[Runtime]:
    built = _seeded(settings, clock, standins())
    try:
        yield built
    finally:
        built.close()


def _board(company: Runtime, at: dt.datetime = _NOW) -> Any:
    with company.database.session() as session:
        return measure_voices(session, at=at, targets=followed_targets(session, at=at))


# ------------------------------------------------------------ the record


def test_a_voice_whose_posts_come_before_the_move_leads_price_and_one_after_trails_it(
    company: Runtime,
) -> None:
    board = _board(company)
    leader = board.voice("x/leader")
    chaser = board.voice("x/chaser")
    assert leader is not None and chaser is not None
    assert (leader.episodes, leader.ahead, leader.after) == (12, 12, Decimal("2.00"))
    assert leader.p_lead == sign_test(12, 12) == Decimal("0.0002")
    assert leader.verdict == "leads price" and not leader.followed
    assert (chaser.ahead, chaser.before_ahead, chaser.before) == (0, 12, Decimal("2.00"))
    assert chaser.verdict == "trails price"
    assert "ahead of peers in the 24h after in 12 of 12" in leader.describe()


def test_a_move_inside_the_bar_the_post_was_made_in_is_never_credited_as_a_lead(
    company: Runtime,
) -> None:
    samebar = _board(company).voice("x/samebar")
    assert samebar is not None
    assert samebar.ahead == 0 and samebar.after == Decimal("0.00")
    assert samebar.before_ahead == samebar.before_episodes == 11, "it counts as the move before"


def test_a_voices_posts_within_a_day_are_one_episode_and_a_record_needs_ten(
    company: Runtime,
) -> None:
    newbie = _board(company).voice("x/newbie")
    assert newbie is not None
    assert (newbie.posts, newbie.instruments, newbie.episodes) == (3, 3, 1)
    assert newbie.verdict == f"gathering (1/{MIN_EPISODES} episodes)" and not newbie.measured


def test_the_bar_a_lead_must_clear_is_divided_by_the_voices_measured(company: Runtime) -> None:
    board = _board(company)
    assert board.measured == 4, "leader, chaser, samebar, quietcalls"
    assert board.bar == Decimal("0.0125")
    assert "4 voice(s) have 10+ episodes" in board.describe_bar()
    quiet = board.voice("telegram/quietcalls")
    assert quiet is not None and quiet.verdict == "no measured lead"
    assert quiet.followed and quiet.origin == "operator"
    assert (quiet.since_follow, quiet.since_follow_ahead) == (11, 0)


def test_an_episode_whose_day_is_not_recorded_yet_is_pending_not_a_miss(
    company: Runtime,
) -> None:
    _post(
        company,
        at=_NOW - dt.timedelta(hours=6),
        instrument="LEAD-USD",
        venue="x/$LEAD",
        author="Leader",
    )
    leader = _board(company).voice("x/leader")
    assert leader is not None
    assert (leader.episodes, leader.ahead, leader.pending) == (12, 12, 1)


def test_only_what_was_recorded_by_the_moment_measured_is_read(
    company: Runtime,
) -> None:
    earlier = _board(company, at=_NOW - dt.timedelta(days=2))
    assert all(v.episodes == 0 for v in earlier.voices), "the prices were fetched later"
    leader = earlier.voice("x/leader")
    assert leader is not None and leader.pending == 12


def test_a_post_from_a_platform_with_no_handle_to_follow_is_not_a_voice(
    company: Runtime,
) -> None:
    assert voice_of({"venue": "cryptocurrency", "author": "someone"}) is None
    assert voice_of({"venue": "x/$LEAD", "author": "Not A Handle!"}) is None
    assert voice_of({"venue": "discord/123456/789012", "author": "a user"}) == (
        "discord",
        "123456/789012",
    )
    assert all(v.platform in ("x", "telegram", "discord") for v in _board(company).voices)


# ------------------------------------------------------------ the seat


class _Curator:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.asked: list[LlmRequest] = []

    def __call__(self, request: LlmRequest) -> str:
        if "Which voices should the company follow" in request.messages[-1].content:
            self.asked.append(request)
            return self.reply
        return standins()(request)


def test_an_agent_follows_and_drops_from_what_the_record_offers(
    settings: Settings, clock: FrozenClock
) -> None:
    curator = _Curator(
        "FOLLOW: x/leader\nDROP: telegram/quietcalls\n"
        "BECAUSE: the leader's posts came before the move in every episode; the channel's "
        "never did.\n"
    )
    company = _seeded(settings, clock, curator)
    try:
        outcome = curate(company, at=_NOW)
        with company.database.session() as session:
            reading = {t.key: t for t in active_targets(session)}
            rows = list(
                session.execute(
                    sa.select(SocialTarget).where(SocialTarget.decided_by == outcome.agent_ref)
                ).scalars()
            )
            event = session.execute(
                sa.text("SELECT actor, payload FROM events WHERE kind = :k"),
                {"k": EventKind.SOCIAL_CURATED.value},
            ).one()
            intel = company.roster.by_handle(session, "INTEL").ref
    finally:
        company.close()
    assert outcome.followed == ("x/leader",) and outcome.dropped == ("telegram/quietcalls",)
    assert ("x", "leader") in reading and ("telegram", "quietcalls") not in reading
    assert len(rows) == 2 and all("Record when" in r.reason for r in rows)
    assert "12 of 12" in next(r.reason for r in rows if r.followed)
    shown = curator.asked[0].messages[-1].content
    assert "x/leader:" in shown and "telegram/quietcalls:" in shown
    assert "x/chaser:" not in shown, "a voice that trails price is not offered"
    assert "x/samebar:" not in shown, "nor one that was never ahead"
    payload = event.payload if isinstance(event.payload, dict) else json.loads(event.payload)
    assert event.actor == intel == outcome.agent_ref
    assert payload["offered_follow"] == ["x/leader"]
    assert payload["offered_drop"] == ["telegram/quietcalls"]
    assert payload["followed"] == ["x/leader"] and len(payload["record"]) == 16
    assert "followed x/leader and dropped telegram/quietcalls" in outcome.describe()


def test_a_reply_naming_a_voice_it_was_not_offered_is_refused_and_changes_nothing(
    settings: Settings, clock: FrozenClock
) -> None:
    curator = _Curator(
        "FOLLOW: x/chaser\nDROP: none\nBECAUSE: it is the loudest account on the token.\n"
    )
    company = _seeded(settings, clock, curator)
    try:
        outcome = curate(company, at=_NOW)
        with company.database.session() as session:
            follows = session.execute(
                sa.select(sa.func.count()).select_from(SocialTarget)
            ).scalar_one()
            due = curation_due(session, _NOW + dt.timedelta(hours=1))
    finally:
        company.close()
    assert outcome.refused and "not offered: x/chaser" in outcome.refused
    assert follows == 1, "only the operator's follow"
    assert not due, "a refused sitting still counts as the day's sitting"
    assert "was refused" in outcome.describe()


def test_with_nothing_eligible_nobody_is_asked_and_no_call_is_made(
    settings: Settings, clock: FrozenClock
) -> None:
    curator = _Curator("FOLLOW: none\nDROP: none\nBECAUSE: nothing to do today at all.\n")
    company = _company(settings, clock, curator)
    try:
        _record_prices(company)
        outcome = curate(company, at=_NOW)
        with company.database.session() as session:
            calls = session.execute(sa.text("SELECT count(*) FROM model_calls")).scalar_one()
    finally:
        company.close()
    assert not outcome.asked and curator.asked == [] and calls == 0
    assert "nothing to decide" in outcome.describe()


def test_the_wake_curates_at_most_once_a_day_under_the_news_grant_and_says_so(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, standins())
    try:
        first_without = cycle_once(
            company, service=Service(company, calls_per_day=50, cycles_per_wake=1)
        )
        with company.database.session() as session:
            company.grants.grant(
                session,
                source="news",
                desk="crypto",
                instruments=("BTC-USD",),
                granted_by="test",
                reason="a test grant, so the wake reads social media",
            )
        first = cycle_once(company, service=Service(company, calls_per_day=50, cycles_per_wake=1))
        clock.advance(hours=2)
        second = cycle_once(company, service=Service(company, calls_per_day=50, cycles_per_wake=1))
        clock.advance(hours=23)
        third = cycle_once(company, service=Service(company, calls_per_day=50, cycles_per_wake=1))
    finally:
        company.close()
    assert "curation:" not in first_without.note, "no social reading, nothing to curate"
    assert "curation:" in first.note and "nothing to decide" in first.note
    assert "curation:" not in second.note, "once a day"
    assert "curation:" in third.note


def test_the_station_shows_every_voices_record_and_every_sitting(
    settings: Settings, clock: FrozenClock
) -> None:
    from aurelis.station.app import station_app

    curator = _Curator(
        "FOLLOW: x/leader\nDROP: none\nBECAUSE: its posts came before the move every time.\n"
    )
    company = _seeded(settings, clock, curator)
    try:
        curate(company, at=_NOW)
        app = station_app(company)
        page = app.handle("/voices", {}).body.decode()
        facility = app.handle("/", {}).body.decode()
    finally:
        company.close()
    assert "<h1>Voices</h1>" in page and "x/leader" in page and "LEADS PRICE" in page
    assert "TRAILS PRICE" in page and "gathering (1/10 episodes)" in page
    assert "its posts came before the move every time" in page
    assert "href='/voices'" in facility
