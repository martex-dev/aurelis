"""Every department's daily duty, run by the service (M56).

The service's wake seats the judging departments, the source analysts and,
when a scheme trades, Risk, the Portfolio Manager and Trading. The Executive,
Audit, Governance, Knowledge and Infrastructure agents had no duty in it: on
the live workspace their rooms read idle, and the record agreed. A company
whose auditors never audit and whose research director never reads the
record is a research desk with an org chart.

So each department holds one duty, run once a day by the agent whose charter
it is, and each duty changes something real:

* **Audit** (the auditor): the ledger chain verifies; no paper round trip
  was held past its horizon; no agent's replies are mostly refused. Each
  failure is an alert on the record, raised by the auditor.
* **Integrity** (the governance officer): every mechanism's seal and every
  view sealed in the last day still hash to what was sealed, and every
  recording fetched in the last day still verifies. A failure is a critical
  alert.
* **Allocation** (the portfolio manager, M57): every scheme's share of the
  paper book re-read against its record after costs and re-sized where the
  ladder in :mod:`aurelis.mechanism.sizing` says otherwise.
* **Health** (the infrastructure agent): how many wakes ran in the last day,
  the longest gap between them, the model calls spent and the alerts left
  open. A gap of more than three hours is an alert.
* **Lessons** (the knowledge agent, one model call): what the last day
  killed, suspended, got worst and dropped, written as one lesson in the
  company's lesson record and a note in the shared brain every seat reads.
* **Memo** (the research director, one model call): the record, the
  mandate, the day's counts and the other duties' findings, written as a
  short memo in the shared brain.

The first three are software and cost nothing. The last two are the only
model calls, and neither is made on a day when nothing happened. A note that
cites a figure the agent was not shown is withheld, as at every seat.

Every run is an ``org.duty_done`` event with the holding agent as its actor,
so the station lights the room of whoever did the work, and the next run
waits a day.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.enums import EventKind, ModelTier

__all__ = [
    "DUTIES",
    "DUTY_EVERY",
    "Duty",
    "DutyResult",
    "duty_due",
    "holder",
    "last_done",
    "run_duties",
]

DUTY_EVERY = dt.timedelta(hours=24)
"""How often each duty runs. A day's record is what each one reads."""

WINDOW = dt.timedelta(hours=24)

MAX_GAP = dt.timedelta(hours=3)
"""A longer gap between two wakes means the service was down."""

REFUSAL_SHARE = 0.5
MIN_ATTEMPTS = 4

_ATTEMPTS = (
    EventKind.THESIS_SEALED.value,
    EventKind.THESIS_DECLINED.value,
    EventKind.THESIS_REFUSED.value,
    EventKind.MECHANISM_STATED.value,
    EventKind.MECHANISM_DECLINED.value,
)
_REFUSALS = (EventKind.THESIS_REFUSED.value,)

_HAPPENINGS = (
    EventKind.THESIS_SEALED.value,
    EventKind.THESIS_SCORED.value,
    EventKind.MECHANISM_STATED.value,
    EventKind.MECHANISM_RETIRED.value,
    EventKind.MECHANISM_TRADED.value,
    EventKind.MECHANISM_SUSPENDED.value,
)
"""What counts as the company having done something worth writing about."""


def _utc(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


@dataclass(frozen=True, slots=True)
class DutyResult:
    """What one duty did."""

    duty: str
    agent_ref: str
    done: str
    findings: tuple[str, ...] = ()
    calls: int = 0

    def describe(self) -> str:
        head = f"{self.duty} ({self.agent_ref}): {self.done}"
        if self.findings:
            return f"{head}; {len(self.findings)} finding(s): " + "; ".join(self.findings[:3])
        return head


@dataclass(frozen=True, slots=True)
class Duty:
    """One department's daily duty and the agent who holds it."""

    key: str
    department: str
    handle: str
    """The launch agent whose charter it is. Anyone active in the department
    stands in when that agent has been split or retired."""

    intent: str
    calls: int
    run: Callable[[Any, Session, str, dt.datetime, list[DutyResult]], DutyResult] = field(
        repr=False
    )


def holder(session: Session, duty: Duty) -> Any:
    """The agent who does the duty: its named holder, or the department's first."""
    from aurelis.agents.tables import Agent, AgentState

    live = [AgentState.ACTIVE.value, AgentState.WORKING.value]
    named = session.execute(
        sa.select(Agent).where(Agent.handle == duty.handle, Agent.state.in_(live))
    ).scalar_one_or_none()
    if named is not None:
        return named
    return (
        session.execute(
            sa.select(Agent)
            .where(Agent.department == duty.department, Agent.state.in_(live))
            .order_by(Agent.ref)
        )
        .scalars()
        .first()
    )


def last_done(session: Session, key: str) -> dt.datetime | None:
    from aurelis.platform.db.tables import Event

    last = session.execute(
        sa.select(sa.func.max(Event.created_at)).where(
            Event.kind == EventKind.DUTY_DONE.value, Event.subject == f"duty:{key}"
        )
    ).scalar()
    return _utc(last) if last is not None else None


def duty_due(session: Session, duty: Duty, at: dt.datetime) -> bool:
    last = last_done(session, duty.key)
    return last is None or _utc(at) - last >= DUTY_EVERY


def _alert(
    runtime: Any,
    session: Session,
    *,
    by: str,
    severity: str,
    source: str,
    subject: str | None,
    message: str,
    action: str,
    at: dt.datetime,
) -> None:
    from aurelis.alerts.service import Severity

    runtime.alerts.raise_alert(
        session,
        severity=Severity(severity),
        source=source,
        subject=subject,
        message=message[:500],
        recommended_action=action,
        raised_by=by,
        at=at,
    )


# ------------------------------------------------------------------ audit


def _audit(
    runtime: Any, session: Session, by: str, at: dt.datetime, _done: list[DutyResult]
) -> DutyResult:
    from aurelis.judgement.tables import Thesis
    from aurelis.mechanism.paper import is_late
    from aurelis.mechanism.tables import MechanismTrade
    from aurelis.platform.db.tables import Event

    since = at - WINDOW
    findings: list[str] = []
    chain = runtime.ledger.verify(session)
    if not chain.ok:
        findings.append(chain.describe())
        _alert(
            runtime,
            session,
            by=by,
            severity="critical",
            source="audit.ledger",
            subject=None,
            message=f"The ledger does not verify: {chain.describe()}",
            action="Stop trusting anything recorded after the break; restore from the "
            "last verified backup and find who wrote past the ledger.",
            at=at,
        )

    late = session.execute(
        sa.select(MechanismTrade, Thesis.resolves_at, Thesis.horizon_hours)
        .join(Thesis, Thesis.ref == MechanismTrade.thesis_ref)
        .where(MechanismTrade.closed_at.is_not(None), MechanismTrade.closed_at >= since)
    ).all()
    held = Counter(
        trade.mechanism_ref for trade, resolves, hours in late if is_late(trade, resolves, hours)
    )
    for mechanism_ref, count in sorted(held.items()):
        findings.append(f"{mechanism_ref}: {count} round trip(s) held past the horizon")
        _alert(
            runtime,
            session,
            by=by,
            severity="warning",
            source="audit.execution",
            subject=mechanism_ref,
            message=f"{count} paper round trip(s) of {mechanism_ref} closed in the last day "
            "were held past their horizon; their P&L is the outage's, not the mechanism's.",
            action="Check the service's wakes for a gap in the last day; the round trips are "
            "already counted apart from the mechanism's record.",
            at=at,
        )

    tally: dict[str, Counter[str]] = {}
    for actor, kind in session.execute(
        sa.select(Event.actor, Event.kind).where(
            Event.kind.in_(_ATTEMPTS), Event.created_at >= since
        )
    ).all():
        tally.setdefault(str(actor), Counter())[str(kind)] += 1
    for actor, kinds in sorted(tally.items()):
        attempts = sum(kinds.values())
        refused = sum(kinds[k] for k in _REFUSALS)
        if attempts >= MIN_ATTEMPTS and refused / attempts > REFUSAL_SHARE:
            findings.append(f"{actor}: {refused} of {attempts} replies refused")
            _alert(
                runtime,
                session,
                by=by,
                severity="warning",
                source="audit.agent",
                subject=actor,
                message=f"{actor} had {refused} of its {attempts} replies in the last day "
                "refused by the seat.",
                action=f"Read its refusals on /agent/{actor}: a figure it keeps inventing, "
                "a form it keeps breaking, or a method that needs replacing.",
                at=at,
            )
    agents = len(tally)
    done = (
        f"{chain.describe()}; {len(late)} round trip(s) closed and {sum(held.values())} "
        f"held late; {agents} agent(s)' replies read"
    )
    return DutyResult("audit", by, done, tuple(findings))


# ------------------------------------------------------------------ integrity


def _integrity(
    runtime: Any, session: Session, by: str, at: dt.datetime, _done: list[DutyResult]
) -> DutyResult:
    from aurelis.intel.snapshots import MarketSnapshot
    from aurelis.judgement.seat import verify_seal as thesis_verifies
    from aurelis.judgement.tables import Thesis
    from aurelis.mechanism.library import verify_seal as mechanism_verifies
    from aurelis.mechanism.tables import Mechanism

    since = at - WINDOW
    findings: list[str] = []
    mechanisms = list(session.execute(sa.select(Mechanism)).scalars())
    broken = [m.ref for m in mechanisms if not mechanism_verifies(m)]
    theses = list(session.execute(sa.select(Thesis).where(Thesis.sealed_at >= since)).scalars())
    broken += [t.ref for t in theses if not thesis_verifies(t)]
    snapshots = list(
        session.execute(
            sa.select(MarketSnapshot.ref).where(MarketSnapshot.fetched_at >= since)
        ).scalars()
    )
    for ref in snapshots:
        ok, detail = runtime.snapshots.verify(session, ref)
        if not ok:
            broken.append(ref)
            findings.append(f"{ref}: {detail}")
    for ref in broken:
        if not any(f.startswith(f"{ref}:") for f in findings):
            findings.append(f"{ref}: no longer hashes to its seal")
        _alert(
            runtime,
            session,
            by=by,
            severity="critical",
            source="integrity.seal",
            subject=ref,
            message=f"{ref} no longer matches what was sealed or recorded.",
            action="Treat every result that cites it as unverified until the change is "
            "explained; a sealed record is never edited.",
            at=at,
        )
    done = (
        f"{len(mechanisms)} mechanism seal(s), {len(theses)} view seal(s) from the last day "
        f"and {len(snapshots)} recording(s) checked; {len(broken)} broken"
    )
    return DutyResult("integrity", by, done, tuple(findings))


# ------------------------------------------------------------------ health


def _health(
    runtime: Any, session: Session, by: str, at: dt.datetime, _done: list[DutyResult]
) -> DutyResult:
    from aurelis.alerts.tables import Alert
    from aurelis.platform.db.tables import Event, ModelCall

    since = at - WINDOW
    wakes = sorted(
        _utc(t)
        for t in session.execute(
            sa.select(Event.created_at).where(
                Event.kind == EventKind.SERVICE_WOKE.value, Event.created_at >= since
            )
        ).scalars()
    )
    gaps = [b - a for a, b in zip(wakes, wakes[1:], strict=False)]
    longest = max(gaps, default=dt.timedelta(0))
    calls = int(
        session.execute(
            sa.select(sa.func.count()).select_from(ModelCall).where(ModelCall.created_at >= since)
        ).scalar_one()
    )
    open_alerts = int(
        session.execute(
            sa.select(sa.func.count()).select_from(Alert).where(Alert.resolved_at.is_(None))
        ).scalar_one()
    )
    findings: list[str] = []
    if longest > MAX_GAP:
        hours = longest.total_seconds() / 3600
        findings.append(f"the service was not awake for {hours:.1f}h")
        _alert(
            runtime,
            session,
            by=by,
            severity="warning",
            source="infra.wakes",
            subject=None,
            message=f"The longest gap between two wakes in the last day was {hours:.1f} hours.",
            action="Check the machine was on and the supervisor script running; "
            "`scripts/run-aurelis.ps1` restarts the service and starts it at logon.",
            at=at,
        )
    done = (
        f"{len(wakes)} wake(s) in the last day, longest gap "
        f"{longest.total_seconds() / 3600:.1f}h; {calls} model call(s); "
        f"{open_alerts} alert(s) open"
    )
    return DutyResult("health", by, done, tuple(findings))


# ------------------------------------------------------------------ allocation


def _allocation(
    runtime: Any, session: Session, by: str, at: dt.datetime, _done: list[DutyResult]
) -> DutyResult:
    from decimal import Decimal

    from aurelis.mechanism.earnings import earnings_board
    from aurelis.mechanism.sizing import room_for, target_weight
    from aurelis.mechanism.tables import Mechanism
    from aurelis.portfolio.tables import Allocation

    board = earnings_board(session)
    changed: list[str] = []
    read = 0
    for mechanism in session.execute(
        sa.select(Mechanism).where(Mechanism.version_ref.is_not(None)).order_by(Mechanism.ref)
    ).scalars():
        version = str(mechanism.version_ref)
        live = list(
            session.execute(
                sa.select(Allocation).where(
                    Allocation.version_ref == version, Allocation.withdrawn_at.is_(None)
                )
            ).scalars()
        )
        for allocation in live:
            read += 1
            target, why = target_weight(board.get(mechanism.ref))
            target = min(target, room_for(runtime, session, allocation.portfolio_ref, version))
            held = Decimal(str(allocation.weight))
            if held == target:
                continue
            runtime.book.withdraw(
                session,
                allocation.ref,
                reason=f"{mechanism.ref} re-sized from {held} to {target}: {why}"[:600],
                withdrawn_by=by,
                at=at,
            )
            if target > 0:
                runtime.book.allocate(
                    session,
                    portfolio_ref=allocation.portfolio_ref,
                    version_ref=version,
                    weight=target,
                    rationale=f"{mechanism.ref} re-sized from its record: {why}"[:600],
                    decided_by=by,
                    at=at,
                )
            changed.append(f"{mechanism.ref}: {held} to {target}")
    return DutyResult(
        "allocation",
        by,
        f"{read} scheme allocation(s) read against their records; {len(changed)} re-sized",
        tuple(changed),
    )


# ------------------------------------------------------------------ the two that think


_FIELD = re.compile(r"^\s*(MEMO|LESSON)\s*:\s*(.*)$", re.I)


def _reply(text: str, key: str) -> str:
    current: str | None = None
    kept: list[str] = []
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).upper()
            if current == key:
                kept.append(match.group(2).strip())
        elif current == key and line.strip():
            kept.append(line.strip())
    return " ".join(kept).strip()


def _ask(
    runtime: Any,
    session: Session,
    *,
    agent_ref: str,
    system: str,
    material: dict[str, Any],
    ask: str,
) -> str:
    from aurelis.agents.interpret import render_material
    from aurelis.brain.briefing import briefing, system_with_brain
    from aurelis.judgement.seat import identity_of
    from aurelis.platform.llm.routing import model_for
    from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

    seated = runtime.roster.get(session, agent_ref)
    tier = seated.authority.tier if seated.authority.tier is not ModelTier.NONE else ModelTier.MID
    response = runtime.provider.complete(
        session,
        LlmRequest(
            model=ModelRef(
                provider=runtime.provider.name,
                model=model_for(runtime.provider.name, tier),
                tier=tier,
                max_tokens=300,
            ),
            system=system_with_brain(system, identity_of(seated, session), briefing(session)),
            messages=(Message("user", f"{render_material(material)}\n\n{ask}"),),
            actor=agent_ref,
        ),
    )
    return str(response.text)


def _happened(session: Session, since: dt.datetime) -> Counter[str]:
    from aurelis.platform.db.tables import Event

    return Counter(
        str(kind)
        for kind in session.execute(
            sa.select(Event.kind).where(Event.kind.in_(_HAPPENINGS), Event.created_at >= since)
        ).scalars()
    )


_LESSON_SYSTEM = (
    "You keep the institutional memory of a quantitative research company. You "
    "are shown what the last day killed, suspended, got most wrong and stopped "
    "reading. Write the one thing the company should remember from it: a trap, a "
    "pattern that failed, a kind of call that keeps missing. Be specific enough "
    "that an analyst could act on it at the next seat. Cite only figures you are "
    "shown. If nothing in it is worth remembering, say so."
)

_LESSON_ASK = (
    "What should the company remember from the last day? Reply in exactly this "
    "form and nothing else:\n"
    "LESSON: <one or two sentences, under 400 characters, or none>\n"
)


def _lessons(
    runtime: Any, session: Session, by: str, at: dt.datetime, _done: list[DutyResult]
) -> DutyResult:
    from aurelis.agents.interpret import allowed_figures, unsourced_numerals
    from aurelis.brain.notes import leave_note
    from aurelis.judgement.tables import Thesis
    from aurelis.mechanism.tables import Mechanism
    from aurelis.platform.db.tables import Event
    from aurelis.social.tables import SocialTarget

    since = at - WINDOW
    retired = list(
        session.execute(
            sa.select(Mechanism).where(Mechanism.retired_at >= since).order_by(Mechanism.ref)
        ).scalars()
    )
    suspended = list(
        session.execute(
            sa.select(Event.subject, Event.payload).where(
                Event.kind == EventKind.MECHANISM_SUSPENDED.value, Event.created_at >= since
            )
        ).all()
    )
    worst = list(
        session.execute(
            sa.select(Thesis)
            .where(Thesis.scored_at >= since, Thesis.brier.is_not(None))
            .order_by(Thesis.brier.desc())
            .limit(5)
        ).scalars()
    )
    dropped = list(
        session.execute(
            sa.select(SocialTarget).where(
                SocialTarget.decided_at >= since, SocialTarget.followed.is_(False)
            )
        ).scalars()
    )
    if not (retired or suspended or worst or dropped):
        return DutyResult("lessons", by, "nothing closed in the last day; no lesson asked for")
    material: dict[str, Any] = {
        "mechanisms_retired": [
            f"{m.ref} {m.title!r} ({m.trigger_kind}, {m.direction} over {m.horizon_hours}h): "
            f"{m.retired_reason[:200]}"
            for m in retired
        ]
        or ["none"],
        "schemes_suspended_for_losing_after_costs": [
            f"{subject}: P&L {p.get('pnl')} over {p.get('episodes')} episode(s)"
            for subject, p in suspended
        ]
        or ["none"],
        "worst_scored_views": [
            f"{t.ref} {t.instrument}: said {t.direction} over {t.horizon_hours}h at "
            f"{t.confidence}, it went {'up' if t.outcome else 'down'}, Brier {t.brier}. "
            f"Why: {' '.join(str(t.thesis).split())[:160]}"
            for t in worst
        ]
        or ["none"],
        "voices_dropped": [f"{d.platform}/{d.handle}: {d.reason[:160]}" for d in dropped]
        or ["none"],
    }
    text = _ask(
        runtime,
        session,
        agent_ref=by,
        system=_LESSON_SYSTEM,
        material=material,
        ask=_LESSON_ASK,
    )
    lesson = _reply(text, "LESSON")
    if not lesson or lesson.lower().rstrip(".") in ("none", "nothing"):
        return DutyResult("lessons", by, "read the day's record and found nothing to keep", calls=1)
    permitted = allowed_figures(material)
    invented = unsourced_numerals(lesson, permitted)
    if invented:
        return DutyResult(
            "lessons",
            by,
            f"lesson withheld: it cited {', '.join(invented[:3])}, which it was not shown",
            calls=1,
        )
    source = (
        retired[0].ref
        if retired
        else (str(suspended[0][0]) if suspended else (worst[0].ref if worst else "social"))
    )
    row = runtime.lessons.record(
        session, statement=lesson[:600], source_ref=source[:24], author=by, at=at
    )
    leave_note(
        session,
        author=by,
        text=lesson,
        topics=("lesson",),
        source_ref=row.ref,
        permitted=permitted,
        ledger=runtime.ledger,
        at=at,
    )
    return DutyResult("lessons", by, f"{row.ref}: {lesson[:160]}", calls=1)


_MEMO_SYSTEM = (
    "You are the research director of a quantitative research company whose "
    "agents work unattended around the clock. Once a day you read the record and "
    "write a short memo that every agent reads at every seat until the next one: "
    "what the evidence says matters now, what to do more of, and what to stop. "
    "You direct attention; you do not decide trades, and you never call anything "
    "profitable that the record does not show earning after costs. Cite only "
    "figures you are shown."
)

_MEMO_ASK = (
    "Write the memo for the next day. Reply in exactly this form and nothing else:\n"
    "MEMO: <at most three sentences, under 400 characters>\n"
)


def _memo(
    runtime: Any, session: Session, by: str, at: dt.datetime, done: list[DutyResult]
) -> DutyResult:
    from aurelis.agents.interpret import allowed_figures, unsourced_numerals
    from aurelis.alerts.tables import Alert
    from aurelis.brain.briefing import briefing
    from aurelis.brain.notes import leave_note
    from aurelis.mandate.tables import MandateAssessment

    since = at - WINDOW
    happened = _happened(session, since)
    if not happened:
        return DutyResult("memo", by, "nothing happened in the last day; no memo written")
    latest = (
        session.execute(
            sa.select(MandateAssessment).order_by(MandateAssessment.assessed_at.desc()).limit(1)
        )
        .scalars()
        .first()
    )
    alerts = list(
        session.execute(
            sa.select(Alert.severity, Alert.message)
            .where(Alert.resolved_at.is_(None))
            .order_by(Alert.raised_at.desc())
            .limit(6)
        ).all()
    )
    material: dict[str, Any] = {
        "the_record": briefing(session).record or "nothing yet",
        "the_mandate": (
            f"{latest.met} of {latest.criteria} conditions met, verdict {latest.verdict}; "
            "unmet: "
            + ", ".join(
                f["key"] for f in (latest.findings or {}).get("criteria", []) if not f.get("met")
            )
            if latest is not None
            else "never assessed"
        ),
        "the_last_day": {kind: str(count) for kind, count in sorted(happened.items())},
        "open_alerts": [f"{severity}: {message[:160]}" for severity, message in alerts] or ["none"],
        "todays_duties": [d.describe() for d in done] or ["none yet"],
    }
    text = _ask(
        runtime, session, agent_ref=by, system=_MEMO_SYSTEM, material=material, ask=_MEMO_ASK
    )
    memo = _reply(text, "MEMO")
    if not memo:
        return DutyResult("memo", by, "the reply held no memo", calls=1)
    permitted = allowed_figures(material)
    invented = unsourced_numerals(memo, permitted)
    if invented:
        return DutyResult(
            "memo",
            by,
            f"memo withheld: it cited {', '.join(invented[:3])}, which it was not shown",
            calls=1,
        )
    note = leave_note(
        session,
        author=by,
        text=memo,
        topics=("memo",),
        source_ref="duty:memo",
        permitted=permitted,
        ledger=runtime.ledger,
        at=at,
    )
    shown = note.ref if note is not None else "unchanged from the last memo"
    return DutyResult("memo", by, f"{shown}: {memo[:160]}", calls=1)


DUTIES: tuple[Duty, ...] = (
    Duty(
        "audit",
        "audit_and_governance",
        "AUDIT",
        "verify the ledger, find round trips held past their horizon, and agents whose "
        "replies are mostly refused",
        0,
        _audit,
    ),
    Duty(
        "integrity",
        "institutional_governance",
        "GOV",
        "check every mechanism's seal, the last day's view seals and recordings",
        0,
        _integrity,
    ),
    Duty(
        "health",
        "infrastructure",
        "INFRA",
        "count the last day's wakes, their longest gap, model calls and open alerts",
        0,
        _health,
    ),
    Duty(
        "allocation",
        "portfolio_and_risk",
        "PM",
        "re-size every scheme's share of the paper book from its record after costs",
        0,
        _allocation,
    ),
    Duty(
        "lessons",
        "knowledge_and_memory",
        "KNOW",
        "write the one lesson the last day's retirements, suspensions and worst calls teach",
        1,
        _lessons,
    ),
    Duty(
        "memo",
        "executive",
        "CIO",
        "read the record and write the memo every agent reads until the next one",
        1,
        _memo,
    ),
)
"""In the order they run: the checks first, so the memo can read what they found."""


def run_duties(
    runtime: Any,
    *,
    at: dt.datetime | None = None,
    calls_left: int = 2,
    only: tuple[str, ...] = (),
    force: bool = False,
) -> list[DutyResult]:
    """Run every duty that is due, inside what is left of the model-call budget.

    A duty that raises is recorded as done with the error, so a broken duty
    waits a day like any other instead of failing every wake.
    """
    moment = _utc(at or runtime.clock.now())
    results: list[DutyResult] = []
    left = calls_left
    for duty in DUTIES:
        if only and duty.key not in only:
            continue
        with runtime.database.session() as session:
            if not force and not duty_due(session, duty, moment):
                continue
            if duty.calls > left:
                continue
            agent = holder(session, duty)
            if agent is None:
                continue
            by = str(agent.ref)
        with runtime.database.session() as session:
            try:
                with session.begin_nested():
                    result = duty.run(runtime, session, by, moment, results)
            except Exception as error:  # noqa: BLE001 - recorded, and the next duty runs
                result = DutyResult(duty.key, by, f"failed: {type(error).__name__}: {error}")
            runtime.ledger.append(
                session,
                kind=EventKind.DUTY_DONE,
                actor=by,
                subject=f"duty:{duty.key}",
                payload={
                    "duty": duty.key,
                    "done": result.done[:300],
                    "findings": [f[:200] for f in result.findings[:10]],
                    "calls": result.calls,
                },
                at=moment,
            )
        results.append(result)
        left -= result.calls
    return results
