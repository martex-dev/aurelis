"""The company taking its own turns, bounded, and stopping when it should.

One cycle is: **assess, choose, act, check whether it moved.** The assessment
is the company's own mandate, so what it works on is decided by the standard it
published rather than by a plan carried in here. The check afterwards is the
half that matters — an action that ran cleanly and moved nothing is the common
case, and a loop that recorded "acted" without recording "moved nothing" would
make a company that achieves nothing look busy.

Three bounds, and each stops the loop *before* it crosses rather than after:

* **cycles** — how many decisions this invocation may take.
* **calls** — model calls. Estimated from the agenda before an action starts,
  so a run cannot discover it is over budget by going over budget.
* **exhaustion** — the real one. When every action that could move something
  unmet has already been taken, the loop stops and says which conditions are
  left and why. See :mod:`aurelis.autonomy.agenda`: the point is that repeating
  a search is not progress, and an unattended loop is exactly where that
  mistake would be made forever.

What the loop cannot do is as deliberate as what it can. It does not fetch data
— that is the one action reaching outside the company, and it needs a person.
It does not trade: there is no live adapter to reach for. It does not lower a
bar it failed to clear, because the bars live in ``mandate/standard.py`` and
nothing here writes to them.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from aurelis.autonomy.agenda import Action, choose, stuck_reasons
from aurelis.autonomy.tables import AutonomyCycle
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import uuid7
from aurelis.mandate.assessment import assess
from aurelis.org.desks import Desk

__all__ = ["AutonomyRun", "CycleRecord", "run_autonomy"]

DEFAULT_CYCLES = 8
DEFAULT_CALLS = 60
"""Bounds an operator gets without asking for more.

Sized from a measured pipeline: authoring is about six model calls, a
five-attempt campaign about fourteen, a review about four. Sixty is room for
the whole agenda once with margin, and not room for anything to run away.
"""


@dataclass(frozen=True, slots=True)
class CycleRecord:
    """What one decision did."""

    n: int
    action: str | None
    reason: str
    outcome: str
    moved: bool
    detail: str
    calls: int

    def describe(self) -> str:
        if self.action is None:
            return f"{self.n}. stopped — {self.reason}"
        mark = "moved" if self.moved else "no change"
        return f"{self.n}. {self.action} — {self.outcome}, {mark}: {self.detail[:90]}"


@dataclass(frozen=True, slots=True)
class AutonomyRun:
    """One invocation: every decision, and where it left the company."""

    run_ref: str
    started_at: dt.datetime
    cycles: tuple[CycleRecord, ...]
    met_before: frozenset[str]
    met_after: frozenset[str]
    stuck: dict[str, str]
    stopped_because: str
    calls: int

    @property
    def gained(self) -> frozenset[str]:
        return self.met_after - self.met_before

    @property
    def acted(self) -> tuple[CycleRecord, ...]:
        return tuple(c for c in self.cycles if c.action is not None)

    def describe(self) -> str:
        lines = [
            f"{self.run_ref}: {len(self.acted)} action(s) over "
            f"{len(self.cycles)} cycle(s), {self.calls} model call(s)",
            *(f"  {c.describe()}" for c in self.cycles),
        ]
        if self.gained:
            lines.append(f"  conditions gained: {', '.join(sorted(self.gained))}")
        else:
            lines.append("  no condition moved")
        lines.append(f"  stopped: {self.stopped_because}")
        return "\n".join(lines)


def _model_calls(runtime: Any) -> int:
    with runtime.database.session() as session:
        return int(
            session.execute(sa.text("SELECT count(*) FROM model_calls")).scalar_one()
        )


def _met(runtime: Any, *, at: dt.datetime) -> frozenset[str]:
    outcome = assess(runtime, at=at)
    return frozenset(f.criterion.key for f in outcome.findings if f.met)


def _unmet(runtime: Any, *, at: dt.datetime) -> frozenset[str]:
    outcome = assess(runtime, at=at)
    return frozenset(f.criterion.key for f in outcome.findings if not f.met)


# ------------------------------------------------------------------- the acts


def _act(runtime: Any, action: Action, *, source: Any, at: dt.datetime) -> str:
    """Run one action and return what it produced, in a sentence.

    Every branch calls machinery that already existed and already has its own
    tests. Nothing is decided here: this is a dispatch table, and it is written
    as one so that "what can the company do unattended?" is answerable by
    reading twenty lines.
    """
    if action.key == "author":
        from aurelis.authoring.attempt import run_authoring

        authored = run_authoring(runtime, desk=Desk.CRYPTO, source=source, at=at)
        return (
            f"{authored.authored.version_ref} {authored.verdict.value}, "
            f"beat baselines: {'yes' if authored.beat_baselines else 'no'}"
        )

    if action.key == "campaign":
        from aurelis.authoring.campaign import run_campaign

        campaign = run_campaign(runtime, desk=Desk.CRYPTO, source=source, at=at)
        check = campaign.selection
        return (
            f"{campaign.campaign_ref}: best {check.observed}, expected best of "
            f"{check.n_trials} is {check.expected_by_chance}, surplus "
            f"{check.surplus}, survives: {'yes' if check.survives else 'no'}"
        )

    if action.key == "review":
        from aurelis.research.review import hold_research_review

        with runtime.database.session() as session:
            handles = {
                name: runtime.roster.by_handle(session, name).ref
                for name in ("QUANT", "CRITIC", "OPS", "GOV", "LEAD-R")
            }
            reviewed = hold_research_review(
                session,
                research=runtime.research,
                chair=runtime.chair,
                author=handles["QUANT"],
                critic=handles["CRITIC"],
                chair_ref=handles["OPS"],
                participants=(handles["QUANT"], handles["CRITIC"], handles["LEAD-R"]),
                registrar=handles["GOV"],
                at=at,
            )
        return reviewed.describe()

    if action.key == "replicate":
        from aurelis.research.replication import Variation

        with runtime.database.session() as session:
            target = session.execute(
                sa.text(
                    "SELECT ref FROM registrations WHERE locked_at IS NOT NULL "
                    "AND ref NOT IN (SELECT parent_registration_ref FROM "
                    "replications) ORDER BY locked_at LIMIT 1"
                )
            ).scalar()
            if target is None:
                return "no locked registration is without a replication"
            report = runtime.replications.replicate(
                session,
                registration_ref=str(target),
                variation=Variation.SEED,
                author=runtime.roster.by_handle(session, "VALID").ref,
                at=at,
            )
        return str(report.describe())

    if action.key == "deploy":
        from aurelis.trading.deployment import deploy, open_paper_book

        with runtime.database.session() as session:
            version = session.execute(
                sa.text(
                    "SELECT version_ref FROM authoring_attempts "
                    "WHERE refused_at IS NULL ORDER BY created_at DESC LIMIT 1"
                )
            ).scalar()
            if version is None:
                return "nothing has been authored, so there is nothing to deploy"
            refs = {
                role: runtime.roster.by_handle(session, handle).ref
                for role, handle in (
                    ("validator", "VALID"),
                    ("governor", "GOV"),
                    ("risk", "RISK"),
                    ("portfolio", "PM"),
                )
            }
            book = open_paper_book(
                runtime,
                session,
                desk="crypto",
                equity=Decimal("100000"),
                opened_by=refs["portfolio"],
                at=at,
            )
            deployment = deploy(
                runtime,
                session,
                version_ref=str(version),
                portfolio_ref=book,
                weight=Decimal("0.25"),
                actors=refs,
                at=at,
            )
        return deployment.describe()

    if action.key == "paper":
        from aurelis.intel.snapshots import latest_snapshot
        from aurelis.trading.paper import measure, walk

        with runtime.database.session() as session:
            snapshot = latest_snapshot(session)
            if snapshot is None:
                return "no snapshot has been recorded, so there is nothing to walk"
            book = session.execute(
                sa.text("SELECT ref FROM portfolios WHERE mode = 'paper' LIMIT 1")
            ).scalar()
            if book is None:
                return "no paper book is open"
            refs = {
                role: runtime.roster.by_handle(session, handle).ref
                for role, handle in (
                    ("proposer", "PM"),
                    ("assessor", "RISK"),
                    ("approver", "TRADE"),
                    ("executor", "TRADE"),
                    ("analyst", "TRADE"),
                )
            }
            walked = walk(
                runtime,
                session,
                portfolio_ref=str(book),
                snapshot=snapshot,
                actors=refs,
                at=at,
            )
            gaps = measure(
                runtime,
                session,
                portfolio_ref=str(book),
                snapshot=snapshot,
                walked=walked,
                at=at,
            )
        return f"{walked.describe()}; {len(gaps)} gap(s) measured"

    raise KeyError(f"no dispatch for action {action.key!r}")


# ------------------------------------------------------------------- the loop


def run_autonomy(
    runtime: Any,
    *,
    cycles: int = DEFAULT_CYCLES,
    calls: int = DEFAULT_CALLS,
    source: Any = None,
    at: dt.datetime | None = None,
) -> AutonomyRun:
    """Let the company work on itself until it runs out of things to do.

    ``source`` is the data every research action measures on. Passed in rather
    than resolved here, because which market the company studies unattended is
    a decision for whoever starts it — and because a loop that picked its own
    data could pick the one its last result looked best on.
    """
    from aurelis.core.ids import RefKind
    from aurelis.platform.db.refs import allocate_ref

    moment = at or runtime.clock.now()
    with runtime.database.session() as session:
        run_ref = allocate_ref(session, RefKind.AUTONOMY_RUN)

    before = _met(runtime, at=moment)
    spent_at_start = _model_calls(runtime)
    records: list[CycleRecord] = []
    failed: set[str] = set()
    stopped = "the cycle limit was reached with work still available"

    for n in range(1, cycles + 1):
        spent = _model_calls(runtime) - spent_at_start
        left = calls - spent
        unmet = _unmet(runtime, at=moment)

        with runtime.database.session() as session:
            decision = choose(
                session, unmet, budget_left=left, failed=frozenset(failed)
            )

        if decision.action is None:
            records.append(
                CycleRecord(n, None, decision.reason, "stopped", False, "", 0)
            )
            _write(runtime, run_ref, records[-1], unmet=unmet, at=moment)
            stopped = decision.reason
            break

        action = decision.action
        started_calls = _model_calls(runtime)
        try:
            detail = _act(runtime, action, source=source, at=moment)
            outcome = "acted"
        except Exception as error:  # noqa: BLE001 - recorded, not swallowed
            # A failed action is a fact about the company, not a crash of the
            # loop, so the run continues. It is also not tried again: the
            # exhaustion rules read persistent state, and a failure usually
            # leaves none -- a refused authoring writes nothing by design, so
            # the rule kept reporting "nothing authored yet" and the loop
            # re-ran it every cycle. Six identical failures, recorded six
            # times, until the cycle bound stopped it.
            detail = f"{type(error).__name__}: {error}"
            outcome = "failed"
            failed.add(action.key)

        after = _met(runtime, at=moment)
        moved = action.condition in after and action.condition not in before
        record = CycleRecord(
            n=n,
            action=action.key,
            reason=decision.reason,
            outcome=outcome,
            moved=moved,
            detail=detail,
            calls=_model_calls(runtime) - started_calls,
        )
        records.append(record)
        _write(runtime, run_ref, record, unmet=unmet, at=moment)

    final = _met(runtime, at=moment)
    with runtime.database.session() as session:
        remaining = stuck_reasons(
            session, frozenset(_unmet(runtime, at=moment))
        )
        runtime.ledger.append(
            session,
            kind=EventKind.AUTONOMY_RUN_FINISHED,
            actor=Actor.SYSTEM,
            subject=run_ref,
            payload={
                "cycles": len(records),
                "acted": sum(1 for r in records if r.action),
                "gained": sorted(final - before),
                "stopped_because": stopped[:200],
            },
            at=moment,
        )

    return AutonomyRun(
        run_ref=run_ref,
        started_at=moment,
        cycles=tuple(records),
        met_before=before,
        met_after=final,
        stuck=remaining,
        stopped_because=stopped,
        calls=_model_calls(runtime) - spent_at_start,
    )


def _write(
    runtime: Any,
    run_ref: str,
    record: CycleRecord,
    *,
    unmet: frozenset[str],
    at: dt.datetime,
) -> None:
    with runtime.database.session() as session:
        session.add(
            AutonomyCycle(
                cycle_id=uuid7(),
                run_ref=run_ref,
                n=record.n,
                unmet=sorted(unmet),
                action=record.action,
                reason=record.reason,
                outcome=record.outcome,
                moved=record.moved,
                detail=record.detail,
                calls=record.calls,
                started_at=at,
                finished_at=at,
            )
        )
        session.flush()
