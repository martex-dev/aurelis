"""Authoring a strategy, preregistered, measured, and charged for.

This is the milestone's demonstration, and the sequence is deliberately in this
order:

.. code-block:: text

    a task is opened and claimed          authoring is work
    the agent is shown the desk           costs, calendar, budget, prior work
    the agent picks a design              1 of 72, from closed slots
    components and a version are written  the agent's words, a cited origin
    the design is preregistered           declaring the WHOLE SPACE as cells
    the experiment runs                   the engine produces every number
    the verdict is derived                by rule, from criteria locked first
    the baselines run                     context, not a registered claim

The agent chooses **before** anything has been run on the data it will be
scored on, so the preregistration is a genuine lock rather than a description
of a decision already made.

Why the whole space is declared
-------------------------------

A grid search that runs seventy-two backtests and reports the best one is a
false discovery machine, and the company already knows it: ``declared_cells``
exists so that a search pays for its own width, and
:meth:`~aurelis.research.lifecycle.Research.trial_count` sums it per family.

An agent choosing one design out of seventy-two looks different — only one
backtest is run — and it is *not*. The agent was shown the alternatives, it
reasoned over them, and nothing in the record can establish which ones it
implicitly weighed. The company therefore charges itself for the space rather
than for the pick. That is the conservative direction, and conservative is the
only defensible direction for a false-discovery denominator: understating it
manufactures confidence out of arithmetic.

Provenance is the exception. Which failure a component answers changes what the
company may claim about having created it and changes no number, so the origin
question is not part of the space. Charging for a choice that cannot move a
result would inflate the denominator as dishonestly as the inert knob would
have deflated it.

What this run actually found
----------------------------

On the crypto desk's fixture, over a quarter of hourly bars, the stand-in's
cost-aware design earns a negative Sharpe and **does not beat holding the
asset**. That is the honest result, it is reported as the headline, and the
system was built so that it could be. The baselines are what make it legible:
a rule that cannot beat buying and holding has not found anything, and one that
cannot beat doing nothing has found less.

**The reasoner is a deterministic stand-in, not a model** — see
:mod:`aurelis.authoring.standin`. What is demonstrated is the machinery.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.authoring.author import (
    AuthoredStrategy,
    AuthoringRefused,
    Citations,
    StrategyAuthor,
)
from aurelis.authoring.design import BASELINES, baseline_spec, space_size
from aurelis.authoring.tables import AuthoringAttempt
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.desks.power import bars_for_span, required_observations
from aurelis.engines.local import LocalEngine
from aurelis.org.desks import DESKS, Desk
from aurelis.platform.db.refs import allocate_ref
from aurelis.research.states import RegistrationKind, Verdict

__all__ = [
    "CAVEAT",
    "caveat_for",
    "data_caveat",
    "CLAIM",
    "SPAN_YEARS",
    "AuthoringOutcome",
    "Baseline",
    "family_for",
    "measure_attempt",
    "run_authoring",
]

SPAN_YEARS = Decimal("0.25")
"""The research budget, in years rather than bars.

Bars are not comparable across desks -- M12's lesson. A quarter of hourly
crypto bars is 2190 observations; the same quarter on the equities calendar is
far fewer, and both are a quarter.
"""

CLAIM = Decimal("0.5")
"""The annualised Sharpe the authored strategy claims, before it is run.

Modest on purpose. A claim large enough to be settled by a short window would
be a claim nobody would make about a real strategy, and a claim small enough to
be unfalsifiable would make UNDERPOWERED the only reachable verdict.
"""

_FIXTURE = (
    "The data is a fixture rather than a market, so no conclusion about any "
    "real market follows from these numbers."
)

CAVEAT = (
    "The designer behind this seat is a deterministic stand-in, not a model. "
    + _FIXTURE
)
"""The offline caveat. True when the mock answers, false the moment one does not.

Kept as the default because every test, every CI run and every offline
demonstration is answered by the stand-in. It is no longer printed
unconditionally: a real model authored a strategy through this exact path and
the report still said a stand-in had done it. A caveat that keeps being printed
after it stops being true is worse than none, because it is the sentence a
reader trusts to tell them what they are looking at.
"""


def caveat_for(provider_name: str, source_name: str = "") -> str:
    """What is actually sitting in the seat and behind the numbers, for this run.

    Takes names rather than objects, so a report can be rendered from a stored
    payload without reconstructing the runtime.

    Both halves are conditional now, and for the same reason. M18 found this
    report still saying a stand-in had answered while a real model was
    answering; M22 found it still saying the data was a fixture while the run
    was measuring three thousand hours of BTC-USD. A caveat is the sentence a
    reader trusts to tell them what they are looking at, and one that survives
    the condition it described is worse than none.
    """
    from aurelis.platform.llm.seating import stands_in

    seat = (
        "The designer behind this seat is a deterministic stand-in, not a model."
        if stands_in(provider_name)
        else (
            f"A real model answered through {provider_name}; the reasoning in "
            "this report is the model's own."
        )
    )
    return f"{seat} {data_caveat(source_name)}"


def data_caveat(source_name: str = "") -> str:
    """What the numbers were measured on.

    A source name that is empty or names a fixture gets the fixture sentence.
    Anything else is a recording of a market, and the caveat that replaces it
    is narrower rather than absent: a snapshot is still one window of one
    instrument, and it stopped at the moment it was fetched.
    """
    if not source_name or source_name.startswith("fixture:"):
        return _FIXTURE
    return (
        f"The numbers were measured on {source_name}, a recording of a real "
        "market. It is one window of one instrument and it stopped at the "
        "moment it was fetched, so nothing here is a claim about what the "
        "market is doing now."
    )


@dataclass(frozen=True, slots=True)
class Baseline:
    """A reference the authored design is read against.

    Explicitly **not** a registered claim. The verdict is derived from criteria
    locked before the run; this comparison is made afterwards and is labelled
    as such everywhere it appears, because a post-hoc comparison presented as a
    test is exactly the move preregistration exists to prevent.
    """

    kind: str
    sharpe: Decimal
    total_return: Decimal

    def describe(self) -> str:
        return f"{self.kind}: sharpe {self.sharpe}, total return {self.total_return}"


@dataclass(frozen=True, slots=True)
class AuthoringOutcome:
    """What one authoring attempt established."""

    authored: AuthoredStrategy
    task_ref: str
    hypothesis_ref: str
    registration_ref: str
    run_ref: str
    verdict: Verdict
    reason: str
    metrics: dict[str, str]
    baselines: tuple[Baseline, ...]
    declared_cells: int
    trials_in_family: int
    attempt_ref: str
    bars: int = 0
    bars_required: int = 0
    years_required: Decimal = Decimal(0)
    campaign_ref: str | None = None
    caveat: str = CAVEAT
    """What sat in the seat for *this* run, resolved when the attempt was made.
    Carried on the outcome rather than looked up at render time, so a report of
    an old attempt says what was true when it happened."""
    sharpe_low: Decimal | None = None
    sharpe_high: Decimal | None = None
    """The interval the run reported, carried so a campaign can recover the
    estimator's standard error without re-running anything. A correction
    computed from an assumed error would be a number with no measurement
    behind it."""
    """What settling the claim would actually have taken.

    Carried on the outcome because UNDERPOWERED without it reads as a defect in
    the design rather than what it is -- a statement about how much data an
    annualised Sharpe claim needs, which on an hourly desk is decades. A report
    that said only "underpowered" would invite somebody to go and tune the
    strategy, which is the wrong response and an expensive one.
    """

    @property
    def shortfall(self) -> int:
        """How many bars short of settling the claim this run was."""
        return max(0, self.bars_required - self.bars)

    @property
    def sharpe(self) -> Decimal:
        return Decimal(self.metrics.get("sharpe", "0"))

    @property
    def total_return(self) -> Decimal:
        return Decimal(self.metrics.get("total_return", "0"))

    @property
    def beat_baselines(self) -> bool:
        """Whether the authored design earned more than every reference.

        On total return rather than Sharpe, because that is the comparison a
        reader means by "did it beat holding the asset" -- and because
        ``never_trade`` has no Sharpe to compare against.
        """
        return all(self.total_return > base.total_return for base in self.baselines)

    def describe(self) -> str:
        verdict = self.verdict.value.upper()
        beat = "beat" if self.beat_baselines else "did NOT beat"
        return (
            f"{self.authored.describe()} -> {verdict}; "
            f"it {beat} the baselines; the search declared "
            f"{self.declared_cells} cells"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt_ref,
            "authored": self.authored.as_payload(),
            "task": self.task_ref,
            "hypothesis": self.hypothesis_ref,
            "registration": self.registration_ref,
            "run": self.run_ref,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "metrics": dict(self.metrics),
            "baselines": [
                {
                    "kind": base.kind,
                    "sharpe": str(base.sharpe),
                    "total_return": str(base.total_return),
                }
                for base in self.baselines
            ],
            "beat_baselines": self.beat_baselines,
            "declared_cells": self.declared_cells,
            "trials_in_family": self.trials_in_family,
            "bars": self.bars,
            "bars_required": self.bars_required,
            "years_required": str(self.years_required),
            "campaign": self.campaign_ref,
            "caveat": self.caveat,
        }


def family_for(desk: Desk | str) -> str:
    """The registration family a desk's authored work is counted in.

    One string, in one place. The multiple-testing denominator is a sum over a
    family prefix, so a second spelling of the same family would silently halve
    it -- which is the direction that manufactures confidence.
    """
    the_desk = desk if isinstance(desk, Desk) else Desk(desk)
    return f"authored.{the_desk.value}"


def run_authoring(
    runtime: Any,
    *,
    desk: Desk | str = Desk.CRYPTO,
    agent_handle: str = "STRAT",
    span: Decimal = SPAN_YEARS,
    declared_cells: int | None = None,
    campaign_ref: str | None = None,
    source: Any | None = None,
    at: dt.datetime | None = None,
) -> AuthoringOutcome:
    """Put an agent in the author's seat and take the result, whatever it is.

    ``declared_cells`` defaults to the whole design space, which is what a
    standalone attempt searched. A campaign passes its own accounting, because
    a revision inside a declared budget searched one slot rather than all of
    them (:mod:`aurelis.authoring.campaign`).

    ``source`` is the data the design will be measured on, and defaults to the
    desk fixture. Passing a recorded market snapshot puts the same agent, the
    same closed space and the same preregistration in front of real bars -- and
    caps the window at what the snapshot actually holds, because a span the
    data cannot cover is a claim about bars that do not exist.

    Raises :class:`~aurelis.authoring.author.AuthoringRefused` if the agent
    fails to produce a whole design; nothing is written in that case, and the
    caller is told which slot it failed on rather than handed a strategy the
    software finished.
    """
    the_desk = desk if isinstance(desk, Desk) else Desk(desk)
    moment = at or runtime.clock.now()
    interval = "1h"
    bars = bars_for_span(the_desk.value, years=span, interval=interval)
    if source is not None:
        available = len(source.bars(source.symbols()[0], limit=0))
        bars = min(bars, available)
        interval = getattr(getattr(source, "snapshot", None), "interval", interval)
    power = required_observations(
        the_desk.value,
        annualised_claim=CLAIM,
        interval=interval,
        bars_available=bars,
    )

    # -------------------------------------------------------- the authoring
    with runtime.database.session() as session:
        seated = runtime.roster.by_handle(session, agent_handle)
        agent_ref = seated.ref
        task = runtime.queue.enqueue(
            session,
            kind="strategy.author",
            assignee=agent_ref,
            payload={"desk": the_desk.value, "space": space_size()},
            actor=Actor.SYSTEM,
            at=moment,
        )
        claimed = runtime.queue.claim(session, worker=agent_ref, at=moment)
        task_ref = claimed.ref if claimed is not None else task.ref

        failure = runtime.research.graveyard(session, limit=1)
        citations = Citations(
            task_ref=task_ref,
            failure_ref=failure[0].ref if failure else None,
        )
        author = StrategyAuthor(
            runtime.provider,
            runtime.synthesis,
            clock=runtime.clock,
            # The Strategy Architect is a HIGH charter. Designing a strategy
            # with the model a routine officer uses would be a cost decision
            # made by a function default.
            tier=seated.authority.tier,
        )
        try:
            authored = author.author(
                session,
                desk=the_desk,
                agent_ref=agent_ref,
                bars=bars,
                citations=citations,
                interval=interval,
                source="" if source is None else source.name,
                task_ref=task_ref,
                at=moment,
            )
        except AuthoringRefused:
            if claimed is not None:
                runtime.queue.fail(session, claimed, error="authoring refused", at=moment)
            raise
        if claimed is not None:
            runtime.queue.succeed(
                session, claimed, result_digest=authored.spec.digest(), at=moment
            )

    return measure_attempt(
        runtime,
        authored,
        task_ref=task_ref,
        bars=bars,
        power=power,
        declared_cells=space_size() if declared_cells is None else declared_cells,
        campaign_ref=campaign_ref,
        source=source,
        at=moment,
    )


def measure_attempt(
    runtime: Any,
    authored: AuthoredStrategy,
    *,
    task_ref: str,
    bars: int,
    power: Any,
    declared_cells: int,
    campaign_ref: str | None = None,
    source: Any | None = None,
    at: dt.datetime | None = None,
) -> AuthoringOutcome:
    """Preregister an authored design, run it, and record what came back.

    Shared by a standalone attempt and by every attempt inside a campaign, so
    there is exactly one path from "an agent designed this" to "the company
    measured it". A second path would be a second definition of what counts as
    a measured attempt, and the two would drift on the first field either of
    them forgot.
    """
    moment = at or runtime.clock.now()
    the_desk = authored.desk
    family = family_for(the_desk)

    with runtime.database.session() as session:
        hypothesis = runtime.research.propose(
            session,
            claim=(
                f"A strategy this company authored earns an annualised Sharpe "
                f"of at least {CLAIM} on the {DESKS[the_desk].name} desk after "
                "that desk's own costs"
            ),
            author=authored.agent_ref,
            minimum_effect=power.per_bar_effect,
            primary_metric="sharpe",
            family=family,
            rationale=(
                f"Designed by {authored.agent_ref} as {authored.design.describe()}, "
                f"one of {space_size()} reachable designs, before any result on "
                f"this data existed. Version {authored.version_ref}."
            ),
            desk=the_desk.value,
            at=moment,
        )
        runtime.research.screen(session, hypothesis.ref, at=moment)
        registration = runtime.research.register(
            session,
            hypothesis_ref=hypothesis.ref,
            spec=authored.spec,
            pass_criteria=[
                {
                    "metric": "sharpe",
                    "comparison": "gte",
                    "value": str(power.per_bar_effect),
                }
            ],
            registrar=_registrar(runtime, session),
            # The space, not the pick. An agent that chose one of seventy-two
            # after reasoning over all of them has searched seventy-two, and
            # the record cannot say otherwise. A revision inside a declared
            # campaign searched one slot, and says that instead.
            declared_cells=declared_cells,
            analysis_plan=(
                "Per-bar Sharpe from the local engine with a block-bootstrap "
                "interval; the lower bound must clear the per-bar equivalent "
                f"of an annualised {CLAIM} on this desk's calendar. The "
                "baselines are run afterwards as context and are not part of "
                "this registration."
            ),
            kind=RegistrationKind.CONFIRMATORY,
            at=moment,
        )
        experiment = runtime.research.design(
            session,
            registration_ref=registration.ref,
            designer=authored.agent_ref,
            at=moment,
        )
        run, artifact = runtime.research.execute(
            session,
            experiment_ref=experiment.ref,
            engine=(
                None
                if source is None
                else LocalEngine(source=source, desk=the_desk.value)
            ),
            at=moment,
        )
        outcome = runtime.research.conclude(
            session,
            run_ref=run.ref,
            artifact=artifact,
            author=authored.agent_ref,
            interpretation=(
                "Authored by an agent from the closed design space and "
                "measured against criteria locked before the run. "
                f"{caveat_for(runtime.provider.name, _source_name(source))}"
            ),
            at=moment,
        )
        trials = runtime.research.trial_count(session, family)
        registration_ref = registration.ref
        hypothesis_ref = hypothesis.ref
        run_ref = run.ref

    sharpe_metric = artifact.metrics.get("sharpe")
    sharpe_low, sharpe_high = sharpe_metric.low, sharpe_metric.high

    # ------------------------------------------------------- the references
    engine = LocalEngine(source=source, desk=the_desk.value)
    baselines = tuple(
        _measure(engine, kind, desk=the_desk, bars=bars, like=authored.spec)
        for kind in BASELINES
    )

    result = AuthoringOutcome(
        authored=authored,
        task_ref=task_ref,
        hypothesis_ref=hypothesis_ref,
        registration_ref=registration_ref,
        run_ref=run_ref,
        verdict=outcome.verdict,
        reason=outcome.report.reason,
        metrics=dict(outcome.metrics),
        baselines=baselines,
        declared_cells=declared_cells,
        trials_in_family=trials,
        attempt_ref="",
        bars=bars,
        bars_required=power.bars_required,
        years_required=power.years_required,
        campaign_ref=campaign_ref,
        caveat=caveat_for(runtime.provider.name, _source_name(source)),
        sharpe_low=sharpe_low,
        sharpe_high=sharpe_high,
    )
    return _record(runtime, result, at=moment)


def _source_name(source: Any | None) -> str:
    """The source's own name, or empty when the desk fixture is in use."""
    return "" if source is None else str(source.name)


def _measure(
    engine: LocalEngine, kind: str, *, desk: Desk, bars: int, like: Any
) -> Baseline:
    artifact = engine.run(baseline_spec(kind, desk=desk, bars=bars, like=like))
    return Baseline(
        kind=kind,
        sharpe=artifact.metrics.get("sharpe").value,
        total_return=artifact.metrics.get("total_return").value,
    )


def _record(
    runtime: Any, outcome: AuthoringOutcome, *, at: dt.datetime
) -> AuthoringOutcome:
    """Write the attempt down, whatever it said."""
    authored = outcome.authored
    with runtime.database.session() as session:
        ref = allocate_ref(session, RefKind.AUTHORING)
        session.add(
            AuthoringAttempt(
                attempt_id=uuid7(),
                ref=ref,
                agent_ref=authored.agent_ref,
                desk=authored.desk.value,
                task_ref=outcome.task_ref,
                design=authored.design.as_payload(),
                design_digest=authored.design.digest(),
                space=space_size(),
                campaign_ref=outcome.campaign_ref,
                origin=authored.origin.value,
                origin_ref=authored.origin_ref,
                strategy_ref=authored.strategy_ref,
                version_ref=authored.version_ref,
                spec_digest=authored.spec.digest(),
                hypothesis_ref=outcome.hypothesis_ref,
                registration_ref=outcome.registration_ref,
                run_ref=outcome.run_ref,
                verdict=outcome.verdict.value,
                declared_cells=outcome.declared_cells,
                trials_in_family=outcome.trials_in_family,
                metrics=dict(outcome.metrics),
                baselines={
                    base.kind: {
                        "sharpe": str(base.sharpe),
                        "total_return": str(base.total_return),
                    }
                    for base in outcome.baselines
                },
                beat_baselines=outcome.beat_baselines,
                created_at=at,
            )
        )
        session.flush()
        runtime.ledger.append(
            session,
            kind=EventKind.STRATEGY_AUTHORED,
            actor=authored.agent_ref,
            subject=ref,
            payload={
                "desk": authored.desk.value,
                "version": authored.version_ref,
                "design": authored.design.as_payload(),
                "space": space_size(),
                "declared_cells": outcome.declared_cells,
                "campaign": outcome.campaign_ref,
                "verdict": outcome.verdict.value,
                "beat_baselines": outcome.beat_baselines,
                "origin": authored.origin.value,
                "origin_ref": authored.origin_ref,
                "caveat": outcome.caveat,
            },
            at=at,
        )

    return AuthoringOutcome(
        authored=outcome.authored,
        task_ref=outcome.task_ref,
        hypothesis_ref=outcome.hypothesis_ref,
        registration_ref=outcome.registration_ref,
        run_ref=outcome.run_ref,
        verdict=outcome.verdict,
        reason=outcome.reason,
        metrics=outcome.metrics,
        baselines=outcome.baselines,
        declared_cells=outcome.declared_cells,
        trials_in_family=outcome.trials_in_family,
        attempt_ref=ref,
        bars=outcome.bars,
        bars_required=outcome.bars_required,
        years_required=outcome.years_required,
        campaign_ref=outcome.campaign_ref,
        caveat=outcome.caveat,
        sharpe_low=outcome.sharpe_low,
        sharpe_high=outcome.sharpe_high,
    )


def _registrar(runtime: Any, session: Any) -> str:
    """Never the author. The lock is worth nothing held by the person it binds."""
    return str(runtime.roster.by_handle(session, "GOV").ref)
