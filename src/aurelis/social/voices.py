"""Whether a voice's posts come before the price moves, or after (M53).

A **voice** is one handle the company could follow: an X account, a Telegram
channel, a Discord channel. Its record is read off the posts already in the
event stream, and nothing here calls a model.

What is measured, for every post a voice made about an instrument the company
records prices for:

* **the move after**: the instrument's return over the next 24 hours, less the
  median return of the other instruments on the same desk over the same 24
  hours. A post on a day everything rose is not a call;
* **the move before**: the same, over the 24 hours before the post. A voice
  that posts after the move is a chaser, and the record says so.

Both are measured between the closes of the bars each end falls inside. A
move inside the bar a post was made in may have come before the post, so it
counts in the move before and never as a lead: an ambiguous move is not
credited to the voice.

Posts are counted by **independent episode**, the rule of ADR-0040: a post
starts an episode, and anything the voice posts within 24 hours of that start
joins it, on any instrument. A voice that posts about ten tokens in an hour
has made one call on the market, not ten.

A voice **leads price** when its episodes were ahead of their peers more often
than a coin would be, by a one-sided sign test, at a bar divided by the number
of voices measured: showing the agents the best of forty records is a search,
and the best of forty coins looks lucky. It **trails price** when, by the same
test, its episodes came after their instrument had already beaten its peers.
Below ten episodes it is gathering.

For a voice the company follows, the episodes since the follow are counted
apart. They are the only ones nobody selected it on.
"""

from __future__ import annotations

import bisect
import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.stats import sign_test
from aurelis.intel.snapshots import MarketSnapshot, SnapshotBar
from aurelis.social.tables import SocialTarget
from aurelis.social.targets import PLATFORMS, NotAHandle, Target, normalise_handle
from aurelis.world.tables import WorldEvent

__all__ = [
    "ALPHA",
    "HORIZON",
    "LOOKBACK",
    "MIN_EPISODES",
    "MIN_PEERS",
    "PriceBook",
    "Voice",
    "VoiceBoard",
    "measure_voices",
    "sign_test",
    "voice_of",
]

HORIZON = dt.timedelta(hours=24)
"""How far after (and before) a post the move is measured, and how long an
episode lasts. The horizon the company's mechanisms and mined patterns use."""

LOOKBACK = dt.timedelta(days=30)
"""How far back posts are read. Older posts are about markets that are gone."""

MIN_EPISODES = 10
"""Episodes a voice needs before its record is read at all: ADR-0040's floor."""

MIN_PEERS = 3
"""Other instruments on the desk needed for a peer median to mean anything."""

ALPHA = Decimal("0.05")
"""The family-wise error rate, before it is divided among the voices."""

_INTERVALS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}

_PCT = Decimal("0.01")
_P = Decimal("0.0001")


def _utc(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def voice_of(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Which voice a recorded post is from, or ``None`` for a platform the
    company cannot follow a handle on (Reddit, Bluesky, Stocktwits).

    A Telegram or Discord post is its channel's. An X post is its author's,
    whether it was read on the author's own timeline or in a cashtag search:
    the search is where the company meets voices it does not follow yet.
    """
    venue = str(payload.get("venue") or "")
    platform, _, rest = venue.partition("/")
    if platform not in PLATFORMS or not rest:
        return None
    raw = str(payload.get("author") or "") if platform == "x" else rest
    try:
        return platform, normalise_handle(platform, raw)
    except NotAHandle:
        return None


# ------------------------------------------------------------------ prices


@dataclass
class _Series:
    desk: str
    step: int
    """The bar interval in seconds."""

    ends: list[dt.datetime]
    """When each bar closed, ascending."""

    closes: list[Decimal]


class PriceBook:
    """Every instrument's closes as of a moment, stitched from its recordings.

    Only what was recorded by ``as_of`` is read, and a bar still open when it
    was fetched is not a close. The newest recording of a bar wins. Only the
    recordings needed to cover the history are read, newest first, so a month
    of hourly fetches is a handful of reads.
    """

    def __init__(self, session: Session, *, as_of: dt.datetime) -> None:
        self._session = session
        self._as_of = _utc(as_of)
        self._series: dict[str, _Series | None] = {}
        self._desks: dict[str, list[str]] = {}
        self._moves: dict[tuple[str, dt.datetime, dt.datetime], Decimal | None] = {}

    def _load(self, symbol: str) -> _Series | None:
        if symbol in self._series:
            return self._series[symbol]
        rows = self._session.execute(
            sa.select(
                MarketSnapshot.ref,
                MarketSnapshot.first_at,
                MarketSnapshot.interval,
                MarketSnapshot.desk,
                MarketSnapshot.fetched_at,
            )
            .where(MarketSnapshot.symbol == symbol, MarketSnapshot.fetched_at <= self._as_of)
            .order_by(MarketSnapshot.fetched_at.desc(), MarketSnapshot.ref.desc())
        ).all()
        if not rows:
            self._series[symbol] = None
            return None
        chosen: dict[str, dt.datetime] = {}
        covered: dt.datetime | None = None
        for ref, first_at, _interval, _desk, fetched_at in rows:
            first = _utc(first_at)
            if covered is None or first < covered:
                chosen[str(ref)] = _utc(fetched_at)
                covered = first
        step = dt.timedelta(seconds=_INTERVALS.get(str(rows[0][2]), 3600))
        rank = {ref: n for n, ref in enumerate(chosen)}  # 0 is the newest
        bars = self._session.execute(
            sa.select(SnapshotBar.snapshot_ref, SnapshotBar.timestamp, SnapshotBar.close).where(
                SnapshotBar.snapshot_ref.in_(list(chosen))
            )
        ).all()
        closes: dict[dt.datetime, Decimal] = {}
        for ref, timestamp, close in sorted(bars, key=lambda b: -rank[str(b[0])]):
            ends = _utc(timestamp) + step
            if ends <= chosen[str(ref)]:
                closes[ends] = Decimal(str(close))
        ordered = sorted(closes)
        series = _Series(
            str(rows[0][3]), int(step.total_seconds()), ordered, [closes[t] for t in ordered]
        )
        self._series[symbol] = series
        return series

    def desk_of(self, symbol: str) -> str | None:
        series = self._load(symbol)
        return series.desk if series is not None else None

    def peers(self, desk: str) -> list[str]:
        if desk not in self._desks:
            self._desks[desk] = sorted(
                str(s)
                for s in self._session.execute(
                    sa.select(MarketSnapshot.symbol).where(MarketSnapshot.desk == desk).distinct()
                ).scalars()
            )
        return self._desks[desk]

    def close_at(self, symbol: str, moment: dt.datetime) -> Decimal | None:
        """The close of the bar ``moment`` falls inside, or ``None``.

        The containing bar, not the last one before: whatever moved inside the
        bar a post was made in may have moved before the post, so it belongs to
        the move before and is never credited as a lead. A bar missing from
        the recordings is a gap, and a gap is an unknown price, not the last
        one seen.
        """
        series = self._load(symbol)
        if series is None:
            return None
        at = bisect.bisect_left(series.ends, moment)
        if at >= len(series.ends):
            return None
        if series.ends[at] - moment > dt.timedelta(seconds=series.step):
            return None
        return series.closes[at]

    def move(self, symbol: str, start: dt.datetime, end: dt.datetime) -> Decimal | None:
        """The instrument's return from ``start`` to ``end``, if both are known."""
        key = (symbol, start, end)
        if key not in self._moves:
            first = self.close_at(symbol, start)
            last = self.close_at(symbol, end)
            self._moves[key] = (
                None if first is None or last is None or first == 0 else last / first - 1
            )
        return self._moves[key]

    def excess(self, symbol: str, start: dt.datetime, end: dt.datetime) -> Decimal | None:
        """The instrument's move less the median of its desk's other instruments."""
        own = self.move(symbol, start, end)
        desk = self.desk_of(symbol)
        if own is None or desk is None:
            return None
        others = [
            m
            for peer in self.peers(desk)
            if peer != symbol and (m := self.move(peer, start, end)) is not None
        ]
        if len(others) < MIN_PEERS:
            return None
        return own - _median(others)


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# ------------------------------------------------------------------ voices


@dataclass
class _Episode:
    start: dt.datetime
    instruments: list[str] = field(default_factory=list)
    after: Decimal | None = None
    before: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Voice:
    """One voice's record, and whether the company follows it."""

    platform: str
    handle: str
    followed: bool
    origin: str | None
    """Who follows it: ``token link``, ``operator``, or an agent's ref."""

    followed_since: dt.datetime | None
    posts: int
    instruments: int
    last_post: dt.datetime | None
    episodes: int
    """Episodes whose move after is known."""

    ahead: int
    """Of those, how many beat their peers over the next 24 hours."""

    after: Decimal | None
    """The median episode's move after the post against its peers, in percent."""

    p_lead: Decimal | None
    before_episodes: int
    before_ahead: int
    before: Decimal | None
    p_trail: Decimal | None
    since_follow: int
    since_follow_ahead: int
    pending: int
    """Episodes too recent, or on instruments without a price, to measure yet."""

    verdict: str

    @property
    def key(self) -> str:
        return f"{self.platform}/{self.handle}"

    @property
    def measured(self) -> bool:
        return self.episodes >= MIN_EPISODES

    def describe(self) -> str:
        if not self.episodes:
            return (
                f"{self.posts} post(s) on {self.instruments} instrument(s), none measurable "
                f"yet ({self.pending} waiting on a price); {self.verdict}"
            )
        parts = [
            f"{self.posts} post(s) on {self.instruments} instrument(s), {self.episodes} "
            f"episode(s) measured",
            f"ahead of peers in the 24h after in {self.ahead} of {self.episodes}, "
            f"median {_signed(self.after)}%",
        ]
        if self.before_episodes:
            parts.append(
                f"its instrument was already ahead in the 24h before in "
                f"{self.before_ahead} of {self.before_episodes}, median {_signed(self.before)}%"
            )
        if self.followed and self.followed_since is not None:
            parts.append(
                f"since followed: ahead in {self.since_follow_ahead} of {self.since_follow}"
            )
        parts.append(self.verdict)
        return "; ".join(parts)


def _signed(value: Decimal | None) -> str:
    if value is None:
        return "?"
    return f"{value:+.2f}"


@dataclass(frozen=True, slots=True)
class VoiceBoard:
    """Every voice measured at one moment, and the bar a lead had to clear."""

    at: dt.datetime
    voices: tuple[Voice, ...]
    measured: int
    """Voices with enough episodes to be read: what the bar is divided by."""

    bar: Decimal

    def followed(self) -> list[Voice]:
        return [v for v in self.voices if v.followed]

    def may_follow(self) -> list[Voice]:
        """What an agent may choose to follow: measured, not followed, and
        ahead of its peers more often than not, without trailing price."""
        return [
            v
            for v in self.voices
            if not v.followed
            and v.measured
            and 2 * v.ahead > v.episodes
            and v.verdict != "trails price"
        ]

    def may_drop(self) -> list[Voice]:
        """What an agent may choose to drop: followed, measured, not leading."""
        return [v for v in self.voices if v.followed and v.measured and v.verdict != "leads price"]

    def voice(self, key: str) -> Voice | None:
        return next((v for v in self.voices if v.key == key), None)

    def describe_bar(self) -> str:
        return (
            f"{self.measured} voice(s) have {MIN_EPISODES}+ episodes, so a lead or a trail "
            f"counts at p < {ALPHA}/{max(self.measured, 1)} = {self.bar}"
        )

    def as_record(self) -> dict[str, Any]:
        """The board as it was shown, for the artifact a curation cites."""
        return {
            "at": self.at.isoformat(),
            "bar": str(self.bar),
            "measured": self.measured,
            "voices": [
                {
                    "voice": v.key,
                    "followed": v.followed,
                    "origin": v.origin,
                    "posts": v.posts,
                    "episodes": v.episodes,
                    "ahead": v.ahead,
                    "after_pct": None if v.after is None else str(v.after),
                    "p_lead": None if v.p_lead is None else str(v.p_lead),
                    "before_episodes": v.before_episodes,
                    "before_ahead": v.before_ahead,
                    "before_pct": None if v.before is None else str(v.before),
                    "p_trail": None if v.p_trail is None else str(v.p_trail),
                    "since_follow": v.since_follow,
                    "since_follow_ahead": v.since_follow_ahead,
                    "verdict": v.verdict,
                }
                for v in self.voices
            ],
        }


@dataclass(frozen=True, slots=True)
class _Gathered:
    key: tuple[str, str]
    items: list[tuple[dt.datetime, str]]
    episodes: list[_Episode]
    origin: str | None
    since: dt.datetime | None

    def after(self) -> list[tuple[dt.datetime, Decimal]]:
        """Each measured episode's start and its move after, against its peers."""
        return [(e.start, e.after) for e in self.episodes if e.after is not None]


def _mean(values: Iterable[Decimal | None]) -> Decimal | None:
    known = [v for v in values if v is not None]
    return sum(known, Decimal(0)) / len(known) if known else None


def _percent(values: list[Decimal]) -> Decimal | None:
    return (_median(values) * 100).quantize(_PCT) if values else None


def _posts(
    session: Session, *, since: dt.datetime, at: dt.datetime
) -> dict[tuple[str, str], list[tuple[dt.datetime, str]]]:
    """Each voice's posts, as (post time, instrument), known by ``at``."""
    venue = WorldEvent.payload["venue"].as_string()
    rows = session.execute(
        sa.select(WorldEvent.at, WorldEvent.entity_key, WorldEvent.payload).where(
            WorldEvent.kind == "social.post",
            WorldEvent.entity_kind == "instrument",
            WorldEvent.at >= since,
            WorldEvent.at <= at,
            WorldEvent.recorded_at <= at,
            sa.or_(*(venue.like(f"{p}/%") for p in PLATFORMS)),
        )
    ).all()
    out: dict[tuple[str, str], list[tuple[dt.datetime, str]]] = {}
    for when, instrument, payload in rows:
        who = voice_of(payload or {})
        if who is not None:
            out.setdefault(who, []).append((_utc(when), str(instrument)))
    return out


def _followed(
    session: Session, targets: Iterable[Target]
) -> dict[tuple[str, str], tuple[str, dt.datetime | None]]:
    """Each followed voice's origin, and when it was last followed on the record."""
    out: dict[tuple[str, str], tuple[str, dt.datetime | None]] = {}
    for target in targets:
        decided = session.execute(
            sa.select(sa.func.max(SocialTarget.decided_at)).where(
                SocialTarget.platform == target.platform,
                SocialTarget.handle == target.handle,
                SocialTarget.followed.is_(True),
            )
        ).scalar()
        out[target.key] = (target.origin, _utc(decided) if decided is not None else None)
    return out


def measure_voices(
    session: Session,
    *,
    at: dt.datetime,
    targets: Iterable[Target] = (),
    horizon: dt.timedelta = HORIZON,
    lookback: dt.timedelta = LOOKBACK,
    prices: PriceBook | None = None,
) -> VoiceBoard:
    """Every voice's record as of ``at``. ``targets`` are the voices followed now."""
    moment = _utc(at)
    book = prices or PriceBook(session, as_of=moment)
    followed = _followed(session, targets)
    posts = _posts(session, since=moment - lookback, at=moment)
    gathered: list[_Gathered] = []
    for key in sorted(set(posts) | set(followed)):
        items = sorted(posts.get(key, []))
        episodes: list[_Episode] = []
        for when, instrument in items:
            if not episodes or when >= episodes[-1].start + horizon:
                episodes.append(_Episode(when))
            if instrument not in episodes[-1].instruments:
                episodes[-1].instruments.append(instrument)
        for episode in episodes:
            if episode.start + horizon > moment:
                continue
            episode.after = _mean(
                book.excess(i, episode.start, episode.start + horizon) for i in episode.instruments
            )
            episode.before = _mean(
                book.excess(i, episode.start - horizon, episode.start) for i in episode.instruments
            )
        origin, since = followed.get(key, (None, None))
        gathered.append(_Gathered(key, items, episodes, origin, since))
    measured = sum(1 for g in gathered if len(g.after()) >= MIN_EPISODES)
    bar = (ALPHA / max(measured, 1)).quantize(_P)
    voices: list[Voice] = []
    for g in gathered:
        after = g.after()
        before = [e.before for e in g.episodes if e.before is not None]
        ahead = sum(1 for _, value in after if value > 0)
        before_ahead = sum(1 for value in before if value > 0)
        later = [value for start, value in after if g.since is not None and start >= g.since]
        p_lead = sign_test(ahead, len(after)) if after else None
        p_trail = sign_test(before_ahead, len(before)) if before else None
        if len(after) < MIN_EPISODES:
            verdict = f"gathering ({len(after)}/{MIN_EPISODES} episodes)"
        elif p_lead is not None and p_lead < bar:
            verdict = "leads price"
        elif len(before) >= MIN_EPISODES and p_trail is not None and p_trail < bar:
            verdict = "trails price"
        else:
            verdict = "no measured lead"
        voices.append(
            Voice(
                platform=g.key[0],
                handle=g.key[1],
                followed=g.origin is not None,
                origin=g.origin,
                followed_since=g.since,
                posts=len(g.items),
                instruments=len({i for _, i in g.items}),
                last_post=g.items[-1][0] if g.items else None,
                episodes=len(after),
                ahead=ahead,
                after=_percent([value for _, value in after]),
                p_lead=p_lead,
                before_episodes=len(before),
                before_ahead=before_ahead,
                before=_percent(before),
                p_trail=p_trail,
                since_follow=len(later),
                since_follow_ahead=sum(1 for value in later if value > 0),
                pending=len(g.episodes) - len(after),
                verdict=verdict,
            )
        )
    voices.sort(
        key=lambda v: (
            not v.followed,
            v.p_lead if v.p_lead is not None else Decimal(2),
            v.key,
        )
    )
    return VoiceBoard(moment, tuple(voices), measured, bar)
