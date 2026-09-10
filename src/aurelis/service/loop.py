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
from aurelis.service.grants import Grants, feed_for
from aurelis.service.tables import DataGrant, ServiceCycle

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
        research_source: Any | None = None,
    ) -> None:
        self.runtime = runtime
        self.calls_per_day = calls_per_day
        self.cycles_per_wake = cycles_per_wake
        self._feeds = feeds or (lambda grant: feed_for(grant, clock=runtime.clock))
        self._research_source = research_source
        self.grants = Grants(runtime.ledger, runtime.clock)
        self._raiser = _operations_director(runtime)

    # ------------------------------------------------------------- the wake

    def wake(self, *, service_ref: str, at: dt.datetime | None = None) -> Wake:
        runtime = self.runtime
        moment = at or runtime.clock.now()
        incidents: list[str] = []
        fetched: list[str] = []
        failures = 0
        notes: list[str] = []

        with runtime.database.session() as session:
            ref = allocate_ref(session, RefKind.SERVICE_CYCLE)
            grants = self.grants.active(session)

        # 1. fetch, under the grants a person recorded
        if not grants:
            notes.append("no active data grant; nothing was fetched")
        for grant in grants:
            for symbol in grant.instruments:
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

        # 2. settle what a recording now covers
        from aurelis.judgement.resolution import resolve_due

        with runtime.database.session() as session:
            results = resolve_due(session, ledger=runtime.ledger, clock=runtime.clock, at=moment)
        scored = sum(1 for r in results if r.scored)
        pending = sum(1 for r in results if not r.scored)

        # 3. work, inside what is left of today
        left = self.calls_per_day - self._calls_since(moment - dt.timedelta(days=1))
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
    try:
        while True:
            at = runtime.clock.now()
            wakes.append(the_service.wake(service_ref=service_ref, at=at))
            if max_wakes is not None and len(wakes) >= max_wakes:
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
