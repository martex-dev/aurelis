"""A search budget, declared first, and the number that survives it.

M15 authored once and stopped, because a revision loop is where authoring turns
into mining and the stopping rule had to be designed before the loop was. This
is the loop with the rule attached, and the rule is two things:

**The budget is declared before the first design exists**, hashed, and frozen
by the database once an attempt has run (:mod:`aurelis.authoring.invariants`).
So is the criterion. A budget raised after seeing the results is a description
of what happened, and a criterion rewritten once the numbers are in is HARKing
with extra steps.

**The best result is corrected for the width of the search that found it**
(:mod:`aurelis.authoring.selection`). Search a space where nothing has an edge,
take the best, and you do not get zero -- you get the largest of *n* draws from
the estimator's own noise. Subtracting that is not pessimism, it is arithmetic.

What the budget buys
--------------------

The agent is allowed to see its own previous result. Nowhere else in this
system may a design be chosen after seeing an answer -- that is selection, and
:mod:`aurelis.authoring.author` shows the author nothing but structure. Inside a
declared campaign it is permitted, because the whole width was declared before
the first attempt and the final number pays for it. That trade is the entire
content of the milestone: **learning from a result is allowed exactly to the
extent that the learning was budgeted for.**

What this run found
-------------------

Every design in the space was swept while building this, and the result is
worth stating plainly because it is a fact about the company rather than about
one campaign:

.. code-block:: text

    best of all 72 designs      sharpe 0.0274
    expected best of 72         sharpe 0.0516 from noise alone
    surplus                     -0.0242

**The best design the company can author is below what searching that wide
returns by chance.** Six trials is already enough to eat it. That is not a
disappointing campaign, it is the answer to "should we search harder?" -- and
the answer is that searching harder raises the bar faster than it finds
anything.

**The reasoner is a deterministic stand-in, not a model**, and every desk runs
on fixtures. What is demonstrated is the machinery.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.authoring.attempt import (
    CAVEAT,
    CLAIM,
    SPAN_YEARS,
    AuthoringOutcome,
    family_for,
    measure_attempt,
    run_authoring,
)
from aurelis.authoring.author import AuthoringRefused, StrategyAuthor
from aurelis.authoring.design import space_size
from aurelis.authoring.revision import (
    REVISABLE,
    revised,
    revision_material,
    revision_space,
    what_to_change_question,
    which_slot_question,
)
from aurelis.authoring.selection import SelectionCheck, check_selection
from aurelis.authoring.tables import Campaign
from aurelis.core.canonical import sha256_of
from aurelis.core.enums import EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.desks.power import bars_for_span, required_observations
from aurelis.org.desks import DESKS, Desk
from aurelis.platform.db.refs import allocate_ref

__all__ = [
    "BUDGET",
    "CRITERION",
    "CampaignOutcome",
    "declared_width",
    "run_campaign",
]

BUDGET = 5
"""Attempts a campaign may make: one authored, four revised.

Small on purpose, and the smallness is the point rather than a limitation. The
correction grows with the width of the search, so a larger budget makes the bar
higher -- and the sweep says the bar is already above anything this space
contains at six trials. A budget chosen to be generous would be a budget chosen
to look thorough.
"""

CRITERION = (
    "The best attempt's Sharpe must exceed what a search of this declared "
    "width returns from noise alone, using the estimator standard error the "
    "run itself reports. Clearing it is the minimum a searched result must do, "
    "not evidence that the strategy works."
)


def declared_width(budget: int = BUDGET) -> int:
    """How many designs a campaign of ``budget`` attempts searches between them.

    The whole space for the first attempt, and the one-slot neighbourhood for
    each revision. Not ``budget * space``: a revision is genuinely a narrower
    search than an authoring, and being accurate is better than being
    conservative when accuracy is available. The conservative rule at M15
    applied to a quantity that could not be measured; this one can.
    """
    if budget < 1:
        raise ValueError("a campaign makes at least one attempt")
    return space_size() + (budget - 1) * REVISABLE


@dataclass(frozen=True, slots=True)
class CampaignOutcome:
    """What a campaign established, including that it established nothing."""

    campaign_ref: str
    desk: Desk
    agent_ref: str
    budget: int
    width: int
    attempts: tuple[AuthoringOutcome, ...]
    refusals: tuple[str, ...]
    selection: SelectionCheck
    trials_in_family: int

    @property
    def best(self) -> AuthoringOutcome | None:
        """The highest Sharpe of the campaign. What a miner would report."""
        if not self.attempts:
            return None
        return max(self.attempts, key=lambda outcome: outcome.sharpe)

    @property
    def improved(self) -> bool:
        """Whether revising moved the number at all, before correction."""
        if len(self.attempts) < 2:
            return False
        return self.attempts[-1].sharpe > self.attempts[0].sharpe

    @property
    def beat_baselines(self) -> bool:
        best = self.best
        return best is not None and best.beat_baselines

    def describe(self) -> str:
        best = self.best
        if best is None:
            return f"{self.campaign_ref}: no attempt completed"
        return (
            f"{self.campaign_ref}: {len(self.attempts)} of {self.budget} "
            f"attempts over {self.width} declared designs; best "
            f"{best.attempt_ref} at sharpe {best.sharpe}; "
            f"{self.selection.describe()}"
        )

    def as_payload(self) -> dict[str, Any]:
        best = self.best
        return {
            "campaign": self.campaign_ref,
            "desk": self.desk.value,
            "agent": self.agent_ref,
            "budget": self.budget,
            "declared_width": self.width,
            "criterion": CRITERION,
            "attempts": [outcome.as_payload() for outcome in self.attempts],
            "refusals": list(self.refusals),
            "best": best.attempt_ref if best is not None else None,
            "selection": self.selection.as_payload(),
            "trials_in_family": self.trials_in_family,
            "beat_baselines": self.beat_baselines,
            "caveat": CAVEAT,
        }


def run_campaign(
    runtime: Any,
    *,
    desk: Desk | str = Desk.CRYPTO,
    agent_handle: str = "STRAT",
    budget: int = BUDGET,
    span: Decimal = SPAN_YEARS,
    at: dt.datetime | None = None,
) -> CampaignOutcome:
    """Author once, revise until the budget runs out, then pay for the search.

    The plan is written and locked **before** the first attempt. Every attempt
    after the first sees what the previous one measured, which is the thing the
    budget buys.
    """
    the_desk = desk if isinstance(desk, Desk) else Desk(desk)
    moment = at or runtime.clock.now()
    width = declared_width(budget)
    interval = "1h"
    bars = bars_for_span(the_desk.value, years=span, interval=interval)
    power = required_observations(
        the_desk.value,
        annualised_claim=CLAIM,
        interval=interval,
        bars_available=bars,
    )

    # ------------------------------------------------- the plan, before anything
    plan = {
        "desk": the_desk.value,
        "budget": budget,
        "declared_width": width,
        "criterion": CRITERION,
        "span_years": str(span),
        "claim": str(CLAIM),
    }
    with runtime.database.session() as session:
        agent_ref = runtime.roster.by_handle(session, agent_handle).ref
        campaign_ref = allocate_ref(session, RefKind.CAMPAIGN)
        session.add(
            Campaign(
                campaign_id=uuid7(),
                ref=campaign_ref,
                desk=the_desk.value,
                agent_ref=agent_ref,
                budget=budget,
                declared_width=width,
                criterion=CRITERION,
                plan_digest=sha256_of(plan),
                locked_at=moment,
            )
        )
        session.flush()
        runtime.ledger.append(
            session,
            kind=EventKind.CAMPAIGN_OPENED,
            actor=agent_ref,
            subject=campaign_ref,
            payload={**plan, "digest": sha256_of(plan)[:16]},
            at=moment,
        )

    # ------------------------------------------------------------ the attempts
    attempts: list[AuthoringOutcome] = []
    refusals: list[str] = []

    try:
        first = run_authoring(
            runtime,
            desk=the_desk,
            agent_handle=agent_handle,
            span=span,
            declared_cells=space_size(),
            campaign_ref=campaign_ref,
            at=moment,
        )
        attempts.append(first)
        _bump(runtime, campaign_ref, at=moment)
    except AuthoringRefused as error:
        refusals.append(f"attempt 1: {error}")

    while attempts and len(attempts) < budget:
        try:
            attempts.append(
                _revise(
                    runtime,
                    previous=attempts[-1],
                    campaign_ref=campaign_ref,
                    attempt=len(attempts) + 1,
                    budget=budget,
                    bars=bars,
                    power=power,
                    interval=interval,
                    at=moment,
                )
            )
            _bump(runtime, campaign_ref, at=moment)
        except (AuthoringRefused, ValueError) as error:
            refusals.append(f"attempt {len(attempts) + 1}: {error}")
            break

    # ----------------------------------------------------- pay for the search
    with runtime.database.session() as session:
        trials = runtime.research.trial_count(session, family_for(the_desk))

    best = max(attempts, key=lambda outcome: outcome.sharpe) if attempts else None
    selection = check_selection(
        observed=best.sharpe if best is not None else Decimal(0),
        low=best.sharpe_low if best is not None else None,
        high=best.sharpe_high if best is not None else None,
        # The declared width, not the number of attempts actually made. A
        # campaign that stopped early still let itself search that wide, and
        # paying only for what it used would reward stopping once ahead.
        n_trials=width,
    )

    outcome = CampaignOutcome(
        campaign_ref=campaign_ref,
        desk=the_desk,
        agent_ref=agent_ref,
        budget=budget,
        width=width,
        attempts=tuple(attempts),
        refusals=tuple(refusals),
        selection=selection,
        trials_in_family=trials,
    )
    _close(runtime, outcome, at=moment)
    return outcome


def _revise(
    runtime: Any,
    *,
    previous: AuthoringOutcome,
    campaign_ref: str,
    attempt: int,
    budget: int,
    bars: int,
    power: Any,
    interval: str,
    at: dt.datetime,
) -> AuthoringOutcome:
    """Ask the agent to change one thing, and measure what it changed it to."""
    authored = previous.authored
    base = _structural(
        authored, bars=bars, interval=interval, task_ref=previous.task_ref
    )
    material = revision_material(
        base,
        design=authored.design,
        metrics=previous.metrics,
        baselines={base.kind: str(base.total_return) for base in previous.baselines},
        attempt=attempt,
        budget=budget,
    )

    with runtime.database.session() as session:
        author = StrategyAuthor(
            runtime.provider,
            runtime.synthesis,
            clock=runtime.clock,
            tier=runtime.roster.get(session, authored.agent_ref).authority.tier,
        )
        which = author.ask_one(
            session,
            agent_ref=authored.agent_ref,
            slot="which_slot",
            question=which_slot_question(authored.design),
            material=material,
            task_ref=previous.task_ref,
        )
        slot = _slot_named(authored.design.family, which)
        what = author.ask_one(
            session,
            agent_ref=authored.agent_ref,
            slot=slot.name,
            question=what_to_change_question(authored.design, slot),
            material=material,
            task_ref=previous.task_ref,
        )
        design = revised(authored.design, slot.name, what)
        revision = author.revise(
            session,
            previous=authored,
            design=design,
            slot_name=slot.name,
            key=what,
            reason=author.turns[-1].reasoning,
            at=at,
        )

    return measure_attempt(
        runtime,
        revision,
        task_ref=previous.task_ref,
        bars=bars,
        power=power,
        # One slot, not the whole space. The campaign already declared the sum
        # of these, so charging the full space here would count the search
        # twice -- and a denominator that is wrong upwards is as untrue as one
        # that is wrong downwards.
        declared_cells=revision_space(authored.design),
        campaign_ref=campaign_ref,
        at=at,
    )


def _structural(
    authored: Any, *, bars: int, interval: str, task_ref: str
) -> dict[str, Any]:
    """The same structural material the first attempt saw.

    Identical on purpose: what a revision adds is the result, and nothing else.
    A revision shown different structure as well would make it impossible to
    say which of the two the agent responded to.
    """
    from aurelis.authoring.author import Citations, material_for

    return material_for(
        authored.desk,
        bars=bars,
        citations=Citations(task_ref=task_ref),
        interval=interval,
    )


def _slot_named(family: str, name: str) -> Any:
    from aurelis.authoring.design import slots_for

    for slot in slots_for(family):
        if slot.name == name:
            return slot
    raise ValueError(f"{name} is not a slot on the {family} branch")


def _bump(runtime: Any, campaign_ref: str, *, at: dt.datetime) -> None:
    """Count the attempt. This is what freezes the plan."""
    import sqlalchemy as sa

    with runtime.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == campaign_ref)
        ).scalar_one()
        row.attempts_run += 1
        session.flush()


def _close(runtime: Any, outcome: CampaignOutcome, *, at: dt.datetime) -> None:
    import sqlalchemy as sa

    best = outcome.best
    with runtime.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == outcome.campaign_ref)
        ).scalar_one()
        row.refusals = len(outcome.refusals)
        row.exhausted = len(outcome.attempts) >= outcome.budget
        row.best_attempt_ref = best.attempt_ref if best is not None else None
        row.best_sharpe = str(outcome.selection.observed)
        row.expected_by_chance = str(outcome.selection.expected_by_chance)
        row.surplus = str(outcome.selection.surplus)
        row.survives_selection = outcome.selection.survives
        row.trials_in_family = outcome.trials_in_family
        row.finished_at = at
        session.flush()

        runtime.ledger.append(
            session,
            kind=EventKind.CAMPAIGN_CLOSED,
            actor=outcome.agent_ref,
            subject=outcome.campaign_ref,
            payload={
                "desk": outcome.desk.value,
                "market": DESKS[outcome.desk].name,
                "attempts": len(outcome.attempts),
                "budget": outcome.budget,
                "declared_width": outcome.width,
                "best": best.attempt_ref if best is not None else None,
                "best_sharpe": str(outcome.selection.observed),
                "expected_by_chance": str(outcome.selection.expected_by_chance),
                "surplus": str(outcome.selection.surplus),
                "survives_selection": outcome.selection.survives,
                "beat_baselines": outcome.beat_baselines,
                "caveat": CAVEAT,
            },
            at=at,
        )
