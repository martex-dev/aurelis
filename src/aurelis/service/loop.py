"""One wake of the service, and the loop that repeats it.

A wake is four steps, in this order, and each step's failure is recorded and
does not stop the next:

1. **Fetch.** For every active grant, every instrument: record a fresh
   snapshot. A vendor that is down is a warning alert; the wake continues.
2. **Settle.** Score every view whose horizon a recording now covers.
3. **Work.** Run the autonomy loop, bounded by what is left of today's
   model-call budget. It seats the judges on the fresh recordings, and it
   still refuses to repeat a search. A provider that is out of allowance is a
   critical alert; the wake continues.
4. **Write.** One row per wake, whatever happened, and the ledger event.

The loop between wakes is deliberately dumb: sleep until the next interval,
stop when the duration is up or somebody interrupts, and say why it stopped.
The clock and the sleeper are injected so a test can run a week in a second.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from aurelis.alerts.service import Severity
from aurelis.core.enums import EventKind
from aurelis.core.errors import ProviderUnavailable
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.live import FeedUnavailable
from aurelis.platform.db.refs import allocate_ref
from aurelis.service.grants import (
    Grants,
    catalogue_for,
    feed_for,
    leverage_for,
    microstructure_for,
    news_for,
)
from aurelis.service.tables import DataGrant, ServiceCycle
from aurelis.world.derive import derive_price_events
from aurelis.world.sources import sync_catalogue

__all__ = ["DEFAULT_CALLS_PER_DAY", "Service", "ServiceOutcome", "Wake", "cycle_once", "serve"]

DEFAULT_CALLS_PER_DAY = 200
"""Model calls the service may spend in a rolling day. A ceiling the loop is
told about before it starts each wake, so a run cannot discover it is over
budget by going over budget."""

SERVICE_ACTOR = "SERVICE"


@dataclass(frozen=True, slots=True)
class Wake:
    """What one wake did."""

    ref: str
    started_at: dt.datetime
    fetched: tuple[str, ...]
    fetch_failures: int
    scored: int
    pending: int
    run_ref: str | None
    calls: int
    calls_left_today: int
    incidents: tuple[str, ...]
    note: str

    def describe(self) -> str:
        parts = [
            f"{self.ref} at {self.started_at:%Y-%m-%d %H:%M}Z:",
            f"fetched {len(self.fetched)}",
            f"scored {self.scored}",
            f"pending {self.pending}",
            f"run {self.run_ref or '—'} ({self.calls} calls, {self.calls_left_today} left today)",
        ]
        if self.incidents:
            parts.append(f"incidents {', '.join(self.incidents)}")
        if self.note:
            parts.append(self.note)
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class ServiceOutcome:
    """One invocation: every wake, and why it stopped."""

    service_ref: str
    wakes: tuple[Wake, ...]
    stopped_because: str
    incidents: tuple[str, ...] = field(default=())

    def describe(self) -> str:
        lines = [f"{self.service_ref}: {len(self.wakes)} wake(s), stopped: {self.stopped_because}"]
        lines += [f"  {wake.describe()}" for wake in self.wakes]
        return "\n".join(lines)


class Service:
    """The working day, wake by wake."""

    def __init__(
        self,
        runtime: Any,
        *,
        calls_per_day: int = DEFAULT_CALLS_PER_DAY,
        cycles_per_wake: int = 40,
        feeds: Callable[[DataGrant], Any] | None = None,
        catalogues: Callable[[DataGrant], Any] | None = None,
        microstructure: Callable[[DataGrant], tuple[Any, Any]] | None = None,
        leverage: Callable[[DataGrant], Any] | None = None,
        news: Callable[[str], Any] | None = None,
        dex: Callable[[DataGrant], Any] | None = None,
        research_source: Any | None = None,
        brain_root: Any = None,
        calls_per_wake: int | None = None,
    ) -> None:
        self.runtime = runtime
        self.calls_per_day = calls_per_day
        self.cycles_per_wake = cycles_per_wake
        self.calls_per_wake = calls_per_wake
        """At most this many model calls in one wake, so a large daily budget
        is spread over the day rather than spent by the first wake (M47)."""
        self._feeds = feeds or (lambda grant: feed_for(grant, clock=runtime.clock))
        self._catalogue = catalogues or catalogue_for
        self._microstructure = microstructure or microstructure_for
        self._leverage = leverage or leverage_for
        self._news = news or news_for
        self._dex = dex or (lambda grant: feed_for(grant, clock=runtime.clock))
        self._research_source = research_source
        self.brain_root = brain_root or (runtime.settings.workspace / "brain")
        # X and Discord are read through this workspace's own browser profile.
        from aurelis.intel.browser import configure

        configure(runtime.settings.workspace)
        """Where the shared brain's Obsidian vault is written each wake."""
        self.grants = Grants(runtime.ledger, runtime.clock)
        self._raiser = _operations_director(runtime)

    # ------------------------------------------------------------- the wake

    def wake(self, *, service_ref: str, at: dt.datetime | None = None) -> Wake:
        runtime = self.runtime
        moment = at or runtime.clock.now()
        incidents: list[str] = []
        fetched: list[str] = []
        failures = 0
        derived = 0
        notes: list[str] = []

        with runtime.database.session() as session:
            ref = allocate_ref(session, RefKind.SERVICE_CYCLE)
            grants = self.grants.active(session)

        # 0. the catalogue, once per live vendor per wake: listings, halts,
        #    delistings become events before any bar is fetched
        catalogue_done: set[str] = set()
        for grant in grants:
            if (
                not grant.is_live
                or grant.is_leverage
                or grant.is_news
                or grant.is_dex
                or grant.source in catalogue_done
            ):
                continue
            catalogue_done.add(grant.source)
            try:
                feed = self._catalogue(grant)
                with runtime.database.session() as session:
                    synced = sync_catalogue(
                        session, runtime.world, feed, clock=runtime.clock, at=moment
                    )
                notes.append(f"catalogue {grant.source}: {synced.describe()}")
            except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                incidents.append(
                    self._incident(
                        severity=Severity.WARNING,
                        source="service.catalogue",
                        subject=grant.source,
                        desk=grant.desk,
                        message=f"catalogue from {grant.source}: {type(error).__name__}: {error}",
                        action="Nothing was recorded. The next wake retries.",
                        at=moment,
                    )
                )

        # 1. fetch, under the grants a person recorded. An instrument on two
        #    grants is fetched once: two permissions are one instrument.
        if not grants:
            notes.append("no active data grant; nothing was fetched")
        fetched_once: set[tuple[str, str]] = set()
        duplicates = 0
        for grant in grants:
            if grant.is_leverage or grant.is_news or grant.is_dex:
                continue
            for symbol in grant.instruments:
                if (grant.source, str(symbol)) in fetched_once:
                    duplicates += 1
                    continue
                fetched_once.add((grant.source, str(symbol)))
                try:
                    feed = self._feeds(grant)
                    with runtime.database.session() as session:
                        snapshot = runtime.snapshots.ingest(
                            session,
                            feed,
                            desk=grant.desk,
                            symbol=str(symbol),
                            interval=grant.interval,
                            bars=grant.bars,
                            is_live=grant.is_live,
                            actor=SERVICE_ACTOR,
                            at=moment,
                        )
                        fetched.append(snapshot.ref)
                        derived += derive_price_events(session, runtime.world, snapshot, at=moment)
                except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                    failures += 1
                    incidents.append(
                        self._incident(
                            severity=Severity.WARNING
                            if isinstance(error, FeedUnavailable)
                            else Severity.CRITICAL,
                            source="service.fetch",
                            subject=f"{grant.ref}:{symbol}",
                            desk=grant.desk,
                            message=(
                                f"{symbol} from {grant.source}: {type(error).__name__}: {error}"
                            ),
                            action=(
                                "Nothing was stored. The next wake retries; if it keeps "
                                "failing, check the vendor and the grant."
                            ),
                            at=moment,
                        )
                    )

        # 1a. tokens, under a dex grant: the rule on the grant names how many
        #     of the tokens the attention sources surfaced are followed, on
        #     which networks, for how long; each followed token's pool bars
        #     are recorded like any instrument's. A token with no pool is one
        #     incident for that token; the wake goes on.
        from aurelis.intel.dex import DexRule, followed_tokens

        followed_keys: list[str] = []
        for grant in grants:
            if not grant.is_dex:
                continue
            rule = DexRule.parse(grant.rule, tuple(str(n) for n in grant.instruments))
            with runtime.database.session() as session:
                following = followed_tokens(session, rule=rule, at=moment)
            recorded = 0
            for key, _liquidity in following:
                if key in followed_keys:
                    continue
                followed_keys.append(key)
                try:
                    feed = self._dex(grant)
                    with runtime.database.session() as session:
                        snapshot = runtime.snapshots.ingest(
                            session,
                            feed,
                            desk=grant.desk,
                            symbol=key,
                            interval=grant.interval,
                            bars=grant.bars,
                            is_live=grant.is_live,
                            actor=SERVICE_ACTOR,
                            at=moment,
                        )
                        fetched.append(snapshot.ref)
                        derived += derive_price_events(session, runtime.world, snapshot, at=moment)
                    recorded += 1
                except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                    failures += 1
                    incidents.append(
                        self._incident(
                            severity=Severity.WARNING
                            if isinstance(error, FeedUnavailable)
                            else Severity.CRITICAL,
                            source="service.fetch",
                            subject=f"{grant.ref}:{key}",
                            desk=grant.desk,
                            message=f"{key} from {grant.source}: {type(error).__name__}: {error}",
                            action=(
                                "Nothing was stored for this token. The next wake retries "
                                "while the rule still follows it."
                            ),
                            at=moment,
                        )
                    )
            notes.append(f"dex: {len(following)} token(s) followed, {recorded} recorded")

        # 2. settle what a recording now covers
        from aurelis.judgement.resolution import resolve_due

        with runtime.database.session() as session:
            results = resolve_due(session, ledger=runtime.ledger, clock=runtime.clock, at=moment)
        scored = sum(1 for r in results if r.scored)
        pending = sum(1 for r in results if not r.scored)

        # 3. work, inside what is left of today
        left = self.calls_per_day - self._calls_since(moment - dt.timedelta(days=1))
        if self.calls_per_wake is not None:
            left = min(left, self.calls_per_wake)
        run_ref: str | None = None
        calls = 0
        if left <= 0:
            notes.append(f"the daily model-call budget of {self.calls_per_day} is spent")
        else:
            from aurelis.autonomy.loop import run_autonomy

            try:
                outcome = run_autonomy(
                    runtime,
                    cycles=self.cycles_per_wake,
                    calls=left,
                    source=self._research_source,
                    at=moment,
                )
                run_ref = outcome.run_ref
                calls = outcome.calls
                if outcome.gained:
                    notes.append(f"conditions gained: {', '.join(sorted(outcome.gained))}")
            except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                incidents.append(
                    self._incident(
                        severity=Severity.CRITICAL,
                        source="service.run",
                        subject=service_ref,
                        desk=None,
                        message=f"{type(error).__name__}: {error}",
                        action=(
                            "The loop did not finish this wake. If the provider is out of "
                            "allowance, the next wake retries when it resets; anything "
                            "else needs a person."
                            if isinstance(error, ProviderUnavailable)
                            else "The loop raised. Read the message; the record up to the "
                            "failure is intact."
                        ),
                        at=moment,
                    )
                )
        left_after = max(0, left - calls)

        if derived:
            notes.append(f"{derived} price event(s) derived")
        if duplicates:
            notes.append(f"{duplicates} instrument(s) on more than one grant, fetched once")

        # 1b. the book and the tape, per live instrument: depth and taker flow
        #     as events, with the raw payloads as artifacts
        from aurelis.intel.microstructure import record_microstructure

        readings = 0
        micro_events = 0
        read_once: set[tuple[str, str]] = set()
        for grant in grants:
            if not grant.is_live or grant.is_leverage or grant.is_news or grant.is_dex:
                continue
            for symbol in grant.instruments:
                if (grant.source, str(symbol)) in read_once:
                    continue
                read_once.add((grant.source, str(symbol)))
                try:
                    book_feed, trades_feed = self._microstructure(grant)
                    with runtime.database.session() as session:
                        _, created = record_microstructure(
                            session,
                            runtime.world,
                            runtime.artifacts,
                            symbol=str(symbol),
                            book_feed=book_feed,
                            trades_feed=trades_feed,
                            clock=runtime.clock,
                            at=moment,
                        )
                    readings += 1
                    micro_events += created
                except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                    incidents.append(
                        self._incident(
                            severity=Severity.WARNING,
                            source="service.microstructure",
                            subject=f"{grant.ref}:{symbol}",
                            desk=grant.desk,
                            message=f"{symbol} book/trades: {type(error).__name__}: {error}",
                            action=(
                                "Nothing was recorded for this instrument; the next wake retries."
                            ),
                            at=moment,
                        )
                    )
        if readings:
            notes.append(f"microstructure: {readings} reading(s), {micro_events} event(s)")

        # 1c. leverage, under its own grant: the funding rate and the open
        #     interest of each spot instrument's perpetual, as events on the
        #     spot instrument. A symbol with no perpetual is counted, not an
        #     incident; a venue that is down is one incident for the grant.
        from aurelis.intel.leverage import perp_for, record_leverage

        lev_readings = lev_events = lev_without = 0
        for grant in grants:
            if not grant.is_leverage:
                continue
            try:
                feed = self._leverage(grant)
                listed = feed.listed()
            except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                incidents.append(
                    self._incident(
                        severity=Severity.WARNING,
                        source="service.leverage",
                        subject=grant.ref,
                        desk=grant.desk,
                        message=f"{grant.source} instruments: {type(error).__name__}: {error}",
                        action="No leverage was recorded this wake; the next retries.",
                        at=moment,
                    )
                )
                continue
            for symbol in grant.instruments:
                if perp_for(str(symbol)) not in listed:
                    lev_without += 1
                    continue
                try:
                    with runtime.database.session() as session:
                        _, created = record_leverage(
                            session,
                            runtime.world,
                            runtime.artifacts,
                            symbol=str(symbol),
                            feed=feed,
                            clock=runtime.clock,
                            at=moment,
                        )
                    lev_readings += 1
                    lev_events += created
                except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                    incidents.append(
                        self._incident(
                            severity=Severity.WARNING,
                            source="service.leverage",
                            subject=f"{grant.ref}:{symbol}",
                            desk=grant.desk,
                            message=f"{symbol} leverage: {type(error).__name__}: {error}",
                            action=(
                                "Nothing was recorded for this instrument; the next wake retries."
                            ),
                            at=moment,
                        )
                    )
        if lev_readings or lev_without:
            notes.append(
                f"leverage: {lev_readings} reading(s), {lev_events} event(s), "
                f"{lev_without} without a perpetual"
            )

        # 1d. sources, under the news grant: whichever catalogue sources the
        #     agents asked for, of any kind, matched against the grant's spot
        #     symbols where the source is about instruments. No request,
        #     nothing read; a keyed source with no key is a note for a person;
        #     a source that is down is one incident. Fetched outside a session,
        #     recorded inside one.
        from aurelis.sources.catalogue import CATALOGUE
        from aurelis.sources.reading import fetch_source, record_source
        from aurelis.sources.seat import active_sources

        news_grants = [g for g in grants if g.is_news]
        if news_grants:
            try:
                with runtime.database.session() as session:
                    wanted = active_sources(session)
            except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                wanted = []
                incidents.append(
                    self._incident(
                        severity=Severity.CRITICAL,
                        source="service.news",
                        subject=news_grants[0].ref,
                        desk=news_grants[0].desk,
                        message=f"reading the source requests: {type(error).__name__}: {error}",
                        action="No source was read this wake. Run `aurelis db init` if the "
                        "schema is behind the code; the next wake retries.",
                        at=moment,
                    )
                )
            symbols = tuple(
                dict.fromkeys(
                    [str(s) for g in news_grants for s in g.instruments] + followed_keys
                )
            )
            names: dict[str, str] = {}
            if followed_keys:
                from aurelis.intel.dex import names_of

                with runtime.database.session() as session:
                    names = names_of(session, tuple(followed_keys))
            # Whom the per-handle readers follow: explicit follows, and each
            # followed token's own published channels (M50).
            from aurelis.social.targets import active_targets

            with runtime.database.session() as session:
                targets = active_targets(session, tokens=tuple(followed_keys))
            read = events = bursts = 0
            for name in wanted:
                source = CATALOGUE[name]
                if not source.available:
                    notes.append(
                        f"{name}: not read, needs {', '.join(source.missing_keys)} in the "
                        "service's environment"
                    )
                    continue
                if source.signin:
                    from aurelis.intel.browser import browser_ready

                    if not browser_ready(source.signin, runtime.settings.workspace):
                        notes.append(
                            f"{name}: not read, needs a person to sign into "
                            f"{source.signin} once: `aurelis social login`"
                        )
                        continue
                try:
                    brought = fetch_source(
                        source,
                        self._news(name),
                        symbols,
                        names=names,
                        targets=targets,
                        rotation=int(moment.timestamp() // 3600),
                    )
                    with runtime.database.session() as session:
                        new_events, new_bursts = record_source(
                            session,
                            runtime.world,
                            runtime.artifacts,
                            fetched=brought,
                            instruments=symbols,
                            clock=runtime.clock,
                            at=moment,
                            names=names,
                        )
                    read += 1
                    events += new_events
                    bursts += new_bursts
                    if source.kind == "telegram":
                        followed = sum(1 for t in targets if t.platform == "telegram")
                        notes.append(
                            f"{name}: {brought.requests} of {followed} followed channel(s) read"
                        )
                    elif source.kind in ("x", "discord"):
                        notes.append(
                            f"{name}: {brought.requests} read, {len(brought.failures)} not"
                        )
                    if brought.failures:
                        asked = brought.requests + len(brought.failures)
                        notes.append(
                            f"{name}: {len(brought.failures)} of {asked} not read "
                            f"({brought.describe_failures()})"
                        )
                except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                    incidents.append(
                        self._incident(
                            severity=Severity.WARNING,
                            source="service.news",
                            subject=f"{news_grants[0].ref}:{name}",
                            desk=news_grants[0].desk,
                            message=f"{name}: {type(error).__name__}: {error}",
                            action="Nothing was recorded from this source; the next wake retries.",
                            at=moment,
                        )
                    )
            if wanted:
                notes.append(f"sources: {read} read, {events} event(s), {bursts} burst(s)")
            else:
                notes.append("sources: no source requested by an agent yet")

        # After new events and settlements, every active mechanism seals
        # predictions on any occurrence it has not yet, and mechanisms that
        # gathered enough evidence and failed are retired.
        from aurelis.mechanism.predictions import generate_all

        with runtime.database.session() as session:
            runs = generate_all(
                session, runtime.mechanisms, ledger=runtime.ledger, clock=runtime.clock, at=moment
            )
            retired = runtime.mechanisms.sweep_retirements(session, at=moment)
        mech_sealed = sum(len(r.sealed) for r in runs)
        if mech_sealed:
            notes.append(f"{mech_sealed} mechanism prediction(s) sealed")
        if retired:
            notes.append(f"{len(retired)} mechanism(s) retired")

        # A candidate scheme trades its firings on paper, through Risk.
        from aurelis.mechanism.paper import (
            books_with_trades,
            close_settled,
            flatten_book,
            has_open_trades,
            trade_firings,
        )

        traded_open = traded_closed = 0
        with runtime.database.session() as session:
            for status in runtime.mechanisms.statuses(session):
                try:
                    # One mechanism's failure is that mechanism's: its work
                    # is rolled back to a savepoint and the others trade.
                    with session.begin_nested():
                        if status.is_scheme:
                            result = trade_firings(runtime, session, status.mechanism, at=moment)
                        elif has_open_trades(session, status.mechanism.ref):
                            # No longer a scheme, still holding: close what has
                            # settled. A position nothing closes is a leak.
                            result = close_settled(runtime, session, status.mechanism, at=moment)
                        else:
                            continue
                except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                    incidents.append(
                        self._incident(
                            severity=Severity.WARNING,
                            source="service.scheme",
                            subject=status.mechanism.ref,
                            desk=status.mechanism.desk,
                            message=f"{type(error).__name__}: {error}",
                            action="The scheme did not trade this wake; the next retries.",
                            at=moment,
                        )
                    )
                    continue
                traded_open += len(result.opened)
                traded_closed += len(result.closed)
            # Whatever the closes left behind: a book is flat in every
            # instrument no open trade accounts for, or the wake says why not.
            flattened = 0
            for book in books_with_trades(session):
                try:
                    swept = flatten_book(runtime, session, book, at=moment)
                except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
                    incidents.append(
                        self._incident(
                            severity=Severity.WARNING,
                            source="service.scheme",
                            subject=book,
                            desk="",
                            message=f"flattening {book}: {type(error).__name__}: {error}",
                            action="The residual stays on the book; the next wake retries.",
                            at=moment,
                        )
                    )
                    continue
                flattened += len(swept.closed)
                if swept.note:
                    notes.append(f"book {book}: {swept.note}")
        if traded_open or traded_closed or flattened:
            notes.append(
                f"schemes: opened {traded_open}, closed {traded_closed}, "
                f"flattened {flattened} paper position(s)"
            )

        # 4b. evolution, once a day: every judging agent's method is measured
        #     on its forward views, and a method significantly worse than a
        #     coin toss is replaced (M48). Its calls count against the day.
        from aurelis.evolution.methods import evolution_due, evolve

        try:
            with runtime.database.session() as session:
                due = evolution_due(session, moment)
            if due and left_after > 0:
                evolved = evolve(runtime, at=moment)
                calls += evolved.calls
                left_after = max(0, left_after - evolved.calls)
                notes.append(evolved.describe())
        except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
            incidents.append(
                self._incident(
                    severity=Severity.WARNING,
                    source="service.evolution",
                    subject=service_ref,
                    desk=None,
                    message=f"evolution did not run: {type(error).__name__}: {error}",
                    action="Methods are unchanged; the next wake retries.",
                    at=moment,
                )
            )

        # 5. the shared brain: the operator's inbox is read into it, and it is
        #    rendered as a vault the operator can open in Obsidian (M46). The
        #    record is the database; a vault that fails to render is a warning.
        from aurelis.brain.vault import sync_brain

        try:
            export = sync_brain(runtime, root=self.brain_root, at=moment)
            notes.append(export.describe())
        except Exception as error:  # noqa: BLE001 - recorded, and the wake continues
            incidents.append(
                self._incident(
                    severity=Severity.WARNING,
                    source="service.brain",
                    subject=service_ref,
                    desk=None,
                    message=f"the shared brain was not synced: {type(error).__name__}: {error}",
                    action=(
                        "The record is intact; the vault is a view of it. The next wake retries."
                    ),
                    at=moment,
                )
            )

        # 4. write it down, whatever it was
        note = "; ".join(notes)
        with runtime.database.session() as session:
            session.add(
                ServiceCycle(
                    cycle_id=uuid7(),
                    ref=ref,
                    service_ref=service_ref,
                    started_at=moment,
                    finished_at=runtime.clock.now(),
                    fetched=list(fetched),
                    fetch_failures=failures,
                    scored=scored,
                    pending=pending,
                    run_ref=run_ref,
                    calls=calls,
                    calls_left_today=left_after,
                    incidents=list(incidents),
                    note=note,
                )
            )
            session.flush()
            runtime.ledger.append(
                session,
                kind=EventKind.SERVICE_WOKE,
                actor=SERVICE_ACTOR,
                subject=ref,
                payload={
                    "service": service_ref,
                    "fetched": list(fetched),
                    "fetch_failures": failures,
                    "scored": scored,
                    "pending": pending,
                    "run": run_ref,
                    "calls": calls,
                    "calls_left_today": left_after,
                    "incidents": list(incidents),
                    "note": note[:300],
                },
                at=moment,
            )
        return Wake(
            ref=ref,
            started_at=moment,
            fetched=tuple(fetched),
            fetch_failures=failures,
            scored=scored,
            pending=pending,
            run_ref=run_ref,
            calls=calls,
            calls_left_today=left_after,
            incidents=tuple(incidents),
            note=note,
        )

    # ------------------------------------------------------------ helpers

    def _calls_since(self, since: dt.datetime) -> int:
        """Model calls the service itself has spent since ``since``.

        Read from the service's own wake rows rather than from ``model_calls``:
        the call records are stamped by the provider's wall clock, and the
        service runs on the runtime's clock, which a test freezes. A budget
        that compared the two would never reset under a frozen clock and
        would be off by the skew under a real one.
        """
        with self.runtime.database.session() as session:
            return int(
                session.execute(
                    sa.select(sa.func.coalesce(sa.func.sum(ServiceCycle.calls), 0)).where(
                        ServiceCycle.started_at >= since
                    )
                ).scalar_one()
            )

    def _incident(
        self,
        *,
        severity: Severity,
        source: str,
        subject: str,
        desk: str | None,
        message: str,
        action: str,
        at: dt.datetime,
    ) -> str:
        if self._raiser is None:
            # An unstaffed workspace has nobody whose charter may raise an
            # alert. The incident still goes on the ledger, as an event.
            with self.runtime.database.session() as session:
                event = self.runtime.ledger.append(
                    session,
                    kind=EventKind.SERVICE_INCIDENT,
                    actor=SERVICE_ACTOR,
                    subject=subject,
                    payload={
                        "severity": severity.value,
                        "source": source,
                        "message": message[:300],
                    },
                    at=at,
                )
                return f"event:{event.seq}"
        with self.runtime.database.session() as session:
            alert = self.runtime.alerts.raise_alert(
                session,
                severity=severity,
                source=source,
                subject=subject,
                desk=desk,
                message=message[:500],
                recommended_action=action,
                raised_by=self._raiser,
                at=at,
            )
            return str(alert.ref)


def _operations_director(runtime: Any) -> str | None:
    """Who raises the service's incidents: the Operations Director.

    System health is that charter's remit and it holds the alert scope. The
    service itself is not an agent and holds no charter, so it cannot write an
    alert in its own name; the write-scope guard would refuse, correctly.
    """
    with runtime.database.session() as session:
        try:
            return str(runtime.roster.by_handle(session, "OPS").ref)
        except KeyError:
            return None


MAX_FAILED_WAKES = 3
"""Consecutive failed wakes after which the service stops and says why.

One failure is an incident and the next wake retries. Three in a row is
something a retry will not fix, and a service that failed every hour for a
week would fill the record with the same incident."""


def _wake_failed(
    service: Service, service_ref: str, error: BaseException, *, at: dt.datetime
) -> None:
    """Record a wake that raised, as a critical incident, and print it."""
    import sys
    import traceback

    traceback.print_exception(error, file=sys.stderr)
    try:
        service._incident(  # noqa: SLF001 - the service's own incident writer
            severity=Severity.CRITICAL,
            source="service.wake",
            subject=service_ref,
            desk=None,
            message=f"the wake raised {type(error).__name__}: {error}",
            action=(
                "The work the wake had committed stands; what it had not is rolled "
                "back. The next wake runs on schedule. If this repeats, read the "
                "message and the traceback in the service window."
            ),
            at=at,
        )
    except Exception as nested:  # noqa: BLE001 - the database itself may be the failure
        print(f"could not record the failed wake: {nested}", file=sys.stderr)


def cycle_once(
    runtime: Any, *, service: Service | None = None, at: dt.datetime | None = None
) -> Wake:
    """One wake, outside a loop. What `aurelis service start --once` runs."""
    the_service = service or Service(runtime)
    moment = at or runtime.clock.now()
    with runtime.database.session() as session:
        service_ref = allocate_ref(session, RefKind.SERVICE)
        runtime.ledger.append(
            session,
            kind=EventKind.SERVICE_STARTED,
            actor=SERVICE_ACTOR,
            subject=service_ref,
            payload={"mode": "once"},
            at=moment,
        )
    wake = the_service.wake(service_ref=service_ref, at=moment)
    _stopped(runtime, service_ref, "one wake, as asked", at=runtime.clock.now())
    return wake


def serve(
    runtime: Any,
    *,
    interval_seconds: int,
    duration_seconds: int | None = None,
    max_wakes: int | None = None,
    service: Service | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> ServiceOutcome:
    """Wake every ``interval_seconds`` until the duration is up or interrupted.

    The wake runs first and the sleep second, so the first wake is immediate.
    The next wake is scheduled from the start of the last one, not from its
    end, so a slow wake does not drift the day.
    """
    import time

    the_service = service or Service(runtime)
    sleep = sleeper or time.sleep
    started = runtime.clock.now()
    with runtime.database.session() as session:
        service_ref = allocate_ref(session, RefKind.SERVICE)
        runtime.ledger.append(
            session,
            kind=EventKind.SERVICE_STARTED,
            actor=SERVICE_ACTOR,
            subject=service_ref,
            payload={
                "interval_seconds": interval_seconds,
                "duration_seconds": duration_seconds,
                "max_wakes": max_wakes,
                "calls_per_day": the_service.calls_per_day,
            },
            at=started,
        )

    wakes: list[Wake] = []
    why = "the duration was reached"
    failed_in_a_row = 0
    attempts = 0
    try:
        while True:
            at = runtime.clock.now()
            attempts += 1
            try:
                wakes.append(the_service.wake(service_ref=service_ref, at=at))
                failed_in_a_row = 0
            except KeyboardInterrupt:
                raise
            except Exception as error:  # noqa: BLE001 - a failed wake is an incident, not the end
                # On 15 September one wake raised and took the service down
                # with it, and nothing was recorded for nine days. A wake that
                # fails is now an incident; the next wake runs on schedule.
                failed_in_a_row += 1
                _wake_failed(the_service, service_ref, error, at=at)
                if failed_in_a_row >= MAX_FAILED_WAKES:
                    why = (
                        f"{failed_in_a_row} wakes in a row failed; the last: "
                        f"{type(error).__name__}: {str(error)[:200]}"
                    )
                    break
            if max_wakes is not None and attempts >= max_wakes:
                why = f"{max_wakes} wake(s), as asked"
                break
            next_at = at + dt.timedelta(seconds=interval_seconds)
            if duration_seconds is not None and next_at >= started + dt.timedelta(
                seconds=duration_seconds
            ):
                break
            pause = (next_at - runtime.clock.now()).total_seconds()
            if pause > 0:
                sleep(pause)
    except KeyboardInterrupt:
        why = "interrupted by the operator"

    _stopped(runtime, service_ref, why, at=runtime.clock.now())
    return ServiceOutcome(
        service_ref=service_ref,
        wakes=tuple(wakes),
        stopped_because=why,
        incidents=tuple(ref for wake in wakes for ref in wake.incidents),
    )


def _stopped(runtime: Any, service_ref: str, why: str, *, at: dt.datetime) -> None:
    with runtime.database.session() as session:
        runtime.ledger.append(
            session,
            kind=EventKind.SERVICE_STOPPED,
            actor=SERVICE_ACTOR,
            subject=service_ref,
            payload={"why": why},
            at=at,
        )
