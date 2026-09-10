"""The author's seat: an agent picks the pieces, and the pieces are the strategy.

M8 built the surface — :func:`~aurelis.strategy.synthesis.Synthesis.author_component`
and :func:`~aurelis.strategy.synthesis.Synthesis.compose` — and said in its own
docstring what it was for: *agents write pieces, with stated reasoning and a
cited origin, and a strategy is what those pieces make.* Until now the pieces
were written by hand in a test fixture. This module is the agent doing it.

Every field the synthesis surface requires is answered by the agent, from a
closed set, in its own words:

============================  ==========================================
what the surface requires     where it comes from now
============================  ==========================================
the signal, and its shape     five design slots (:mod:`.design`)
``rationale``                 the agent's ``BECAUSE`` for that slot
``origin`` / ``origin_ref``   a closed provenance question
``known_weaknesses``          a closed question, abstention refused
``assumes``                   implied by the choice, not asserted
============================  ==========================================

Three refusals hold the seat shut.

**A half-authored strategy is not a strategy.** If any turn is unreadable, or
cites a figure nobody showed the agent, the whole authoring is refused and
nothing is written. Composing around a missing answer would put the software's
default into the agent's record and call it the agent's design.

**A component with no origin is not authored.** ``NOTHING`` is offered on every
question because a decision surface without abstention produces an agent that
always finds something — but abstaining on provenance is refused, because
:class:`~aurelis.strategy.states.Origin` is the field the company's claim to
have *created* anything rests on, and an uncited creation is unfalsifiable.

**A composition whose author cannot name a weakness is refused**, which is M8's
rule, now answered by the agent rather than by a fixture. Every strategy has a
regime it does not survive; an agent that abstains has not looked.

What sits behind the seat in this repository is a deterministic stand-in, not a
model — the same caveat as M14, for the same reason, and it is repeated on
every report.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from aurelis.agents.decide import Choice, Decision, Question, decide_as
from aurelis.agents.interpret import UnsourcedFigures
from aurelis.authoring.design import (
    FAMILY,
    Design,
    Slot,
    component_spec,
    question_for,
    render,
    slots_for,
    space_size,
)
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import ModelTier
from aurelis.desks.calendars import calendar_for
from aurelis.desks.costs import costs_for
from aurelis.engines.spec import ExperimentSpec
from aurelis.org.desks import DESKS, Desk
from aurelis.strategy.markets import Assumption
from aurelis.strategy.states import Origin
from aurelis.strategy.synthesis import Novelty, Synthesis
from aurelis.strategy.tables import Component

__all__ = [
    "MATERIAL_SECTIONS",
    "WEAKNESSES",
    "AuthorTurn",
    "AuthoredStrategy",
    "AuthoringRefused",
    "Citations",
    "StrategyAuthor",
    "material_for",
    "origin_question",
    "weakness_question",
]

SYSTEM = (
    "You are a strategy architect at a quantitative research company. You are "
    "choosing one design from a fixed menu, for one market desk. The company "
    "will then preregister your choice, measure it against criteria fixed "
    "before the run, and refute it if the evidence says so.\n\n"
    "Choosing a design is NOT a claim that it works. It is choosing what to "
    "test next. The data available is described below and may be short or "
    "synthetic; that is a fact about this experiment, not a reason to decline "
    "to design one. Reserve `nothing` for when no option could be tested at "
    "all, not for when you are uncertain whether it will succeed.\n\n"
    "You do not choose the costs, the universe or the window; those belong to "
    "the desk."
)
"""What the seat is, said plainly enough that a careful model will sit in it.

The first version said "you are designing a strategy" and nothing else. A real
model, shown honestly that the data is a fixture and only 2190 bars long,
answered `nothing` **three times in five** -- and its reasons were sound: it was
declining to claim an edge on synthetic data too short to support one.

That is the right instinct pointed at the wrong question. The seat does not ask
for a claim; it asks which design the company should test next, and the answer
is measured and frequently refuted. Saying so is not coaxing the model into
compliance, it is telling it the truth about what its answer will be used for --
and the abstention rate went to zero without weakening a single guard.
"""

WEAKNESSES: tuple[Choice, ...] = (
    Choice("trending", "a market that keeps going will run over a reversion rule"),
    Choice("choppy", "a market with no direction pays the costs and earns nothing"),
    Choice("cost_shock", "the edge is thin enough that wider spreads erase it"),
    Choice("regime_break", "the relationship it trades on may simply stop holding"),
    Choice("crowding", "the same rule is obvious enough that others may take it"),
)
"""What a strategy might not survive. Closed, and an abstention is refused.

Not a design choice — naming a weakness does not change what runs. It is
required because :func:`~aurelis.strategy.synthesis.Synthesis.compose` refuses
a version whose authors cannot name one, and that rule was written at M8 on the
grounds that every composition has a regime it fails in and authors who cannot
say which have not looked. The agent now answers it.
"""

MATERIAL_SECTIONS: tuple[str, ...] = ("desk", "costs", "budget", "prior_work")
"""Everything the author is shown, and nothing else.

None of it is a result. The agent designs the strategy **before** anything has
been run on the data it will be scored against, which is what makes the
preregistration that follows worth locking: an author shown this quarter's
Sharpe for each candidate would be selecting, not authoring, and the
registration would be a record of a decision already made.
"""


@dataclass(frozen=True, slots=True)
class Citations:
    """What the agent may claim its work came from.

    Each entry is a reference that already exists in the company's record.
    The agent chooses *which* provenance applies; it cannot write the citation
    itself, because a free-text origin is exactly the unfalsifiable claim
    :mod:`aurelis.strategy.synthesis` refuses.
    """

    task_ref: str | None = None
    """The task the authoring was done under. Supports ``INVENTED``."""

    failure_ref: str | None = None
    """A hypothesis the company already killed. Supports
    ``DERIVED_FROM_FAILURE``, and it is what a graveyard is for."""

    corpus_ref: str | None = None
    """An inherited trial. Supports ``ADAPTED`` — an honest inheritance."""

    def available(self) -> tuple[tuple[Origin, str], ...]:
        pairs: list[tuple[Origin, str]] = []
        if self.failure_ref:
            pairs.append((Origin.DERIVED_FROM_FAILURE, self.failure_ref))
        if self.corpus_ref:
            pairs.append((Origin.ADAPTED, self.corpus_ref))
        if self.task_ref:
            pairs.append((Origin.INVENTED, self.task_ref))
        return tuple(pairs)


class AuthoringRefused(RuntimeError):
    """The agent did not produce a design, so nothing was written.

    Carries the slot it failed on. A partial composition is not a lesser
    strategy, it is a strategy the software finished — and that is the one
    thing this seat exists to prevent.
    """

    def __init__(self, slot: str, cause: Exception) -> None:
        super().__init__(
            f"authoring refused at {slot!r}: {cause}. A half-authored strategy "
            "would be finished by the software and recorded as the agent's "
            "design, so nothing is written."
        )
        self.slot = slot
        self.cause = cause


@dataclass(frozen=True, slots=True)
class AuthorTurn:
    """One question, and what came back."""

    slot: str
    chosen: tuple[str, ...]
    reasoning: str
    refused: bool = False
    error: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "chosen": list(self.chosen),
            "reasoning": self.reasoning,
            "refused": self.refused,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class AuthoredStrategy:
    """A strategy an agent designed, and the record of it designing it."""

    agent_ref: str
    desk: Desk
    strategy_ref: str
    version_ref: str
    design: Design
    spec: ExperimentSpec
    origin: Origin
    origin_ref: str
    weaknesses: tuple[str, ...]
    components: tuple[Component, ...] = field(default=())
    turns: tuple[AuthorTurn, ...] = field(default=())
    novelty: Novelty | None = None

    @property
    def space(self) -> int:
        """How many designs the agent chose between."""
        return space_size()

    def describe(self) -> str:
        return (
            f"{self.agent_ref} authored {self.version_ref} on "
            f"{self.desk.value}: {self.design.describe()} "
            f"(1 of {self.space} reachable designs)"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "agent": self.agent_ref,
            "desk": self.desk.value,
            "strategy": self.strategy_ref,
            "version": self.version_ref,
            "design": self.design.as_payload(),
            "design_digest": self.design.digest(),
            "spec_digest": self.spec.digest(),
            "origin": self.origin.value,
            "origin_ref": self.origin_ref,
            "weaknesses": list(self.weaknesses),
            "space": self.space,
            "turns": [turn.as_payload() for turn in self.turns],
        }


def material_for(
    desk: Desk | str,
    *,
    bars: int,
    citations: Citations,
    interval: str = "1h",
    source: str = "",
) -> dict[str, Any]:
    """Everything the author gets to see. A pure function of the desk.

    No session, no engine, no artifact — deliberately, and the signature is the
    guarantee. There is nothing here that could carry a measurement of the data
    the design will be scored on, so the design cannot have been chosen for
    fitting it.
    """
    the_desk = desk if isinstance(desk, Desk) else Desk(desk)
    costs = costs_for(the_desk)
    calendar = calendar_for(the_desk.value)
    prior: dict[str, Any] = {}
    if citations.failure_ref:
        prior["a hypothesis this company killed"] = citations.failure_ref
    if citations.corpus_ref:
        prior["an inherited trial"] = citations.corpus_ref
    if citations.task_ref:
        prior["the task you are authoring under"] = citations.task_ref
    if not prior:
        prior["nothing"] = "the company has no prior work to cite here"

    return {
        "desk": {
            "market": DESKS[the_desk].name,
            "calendar": calendar.name,
            # Named, because this line was a flat "fixture, not live market
            # data" and stayed that way when the seat was first pointed at a
            # recording of a real market. An agent briefed with a false fact
            # about its own data is being asked to reason about a different
            # problem than the one it is scored on.
            "data": (
                f"recorded market data: {source}"
                if source
                else "fixture, not live market data"
            ),
        },
        "costs": {
            "round trip": f"{costs.round_trip_bps} bps",
            "who sets them": "the desk, not you",
        },
        "budget": {
            "bars available": bars,
            "interval": interval,
            "bars a year on this calendar": calendar.periods_per_year(interval),
        },
        "prior_work": prior,
    }


def origin_question(citations: Citations) -> Question:
    """Where did this come from? Closed, and abstention is refused.

    The options are the citations that already exist in the record. An agent
    cannot write its own, because the citation shape check in
    :mod:`aurelis.strategy.synthesis` can only tell an invented component from
    a copied one if the reference is real.
    """
    describes = {
        Origin.DERIVED_FROM_FAILURE: "it answers a failure the company recorded",
        Origin.ADAPTED: "it is taken from inherited work and changed",
        Origin.INVENTED: "it was reasoned out here, under this task",
    }
    options = tuple(
        Choice(origin.value, f"{describes[origin]} ({ref})")
        for origin, ref in citations.available()
    )
    if not options:
        raise ValueError(
            "no citation is available, so no origin can be claimed. An "
            "uncited origin makes 'we created this' unfalsifiable"
        )
    return Question(
        prompt="Where did this design come from?", options=options, multiple=False
    )


def weakness_question() -> Question:
    return Question(
        prompt="What will this strategy not survive?",
        options=WEAKNESSES,
        multiple=True,
    )


class StrategyAuthor:
    """Drives an agent through the design space and writes what it chose."""

    __slots__ = ("_provider", "_synthesis", "_clock", "tier", "turns")

    def __init__(
        self,
        provider: Any,
        synthesis: Synthesis,
        *,
        clock: Clock | None = None,
        tier: ModelTier = ModelTier.MID,
    ) -> None:
        self._provider = provider
        self._synthesis = synthesis
        self._clock = clock or SystemClock()
        self.tier = tier
        """Which model answers. The **agent's own** tier, resolved from the
        charters it covers, passed in by whoever seated it -- not a default
        chosen by this signature. A Strategy Architect is a HIGH charter and
        should not design with the model a source-reliability officer uses."""
        self.turns: list[AuthorTurn] = []

    # ------------------------------------------------------------- asking

    def _ask(
        self,
        session: Session,
        *,
        agent_ref: str,
        slot: str,
        question: Question,
        material: dict[str, Any],
        task_ref: str | None,
    ) -> Decision:
        try:
            decision = decide_as(
                self._provider,
                session,
                agent_ref=agent_ref,
                question=question,
                material=material,
                system=SYSTEM,
                tier=self.tier,
                task_ref=task_ref,
            )
        except (UnsourcedFigures, ValueError) as error:
            self.turns.append(
                AuthorTurn(
                    slot=slot,
                    chosen=(),
                    reasoning="",
                    refused=True,
                    error=f"{type(error).__name__}: {error}",
                )
            )
            raise AuthoringRefused(slot, error) from error

        self.turns.append(
            AuthorTurn(
                slot=slot,
                chosen=tuple(sorted(decision.chosen)),
                reasoning=decision.reasoning,
            )
        )
        return decision

    def ask_one(
        self,
        session: Session,
        *,
        agent_ref: str,
        slot: str,
        question: Question,
        material: dict[str, Any],
        task_ref: str | None = None,
    ) -> str:
        """Ask one closed question and return the single key chosen.

        Public because a revision is the same seat asking a different question,
        and a campaign that reimplemented the ask would have its own parse, its
        own figure check and its own idea of what a refusal is.
        """
        return self._one(
            self._ask(
                session,
                agent_ref=agent_ref,
                slot=slot,
                question=question,
                material=material,
                task_ref=task_ref,
            ),
            slot,
        )

    @staticmethod
    def _one(decision: Decision, slot: str) -> str:
        if decision.abstained:
            raise AuthoringRefused(
                slot,
                ValueError(
                    f"the agent abstained on {slot}, which has no default. A "
                    "software default recorded as the agent's choice would "
                    "make the design partly the company's and wholly the "
                    "agent's on the record"
                ),
            )
        return next(iter(decision.chosen))

    # ------------------------------------------------------------ writing

    def author(
        self,
        session: Session,
        *,
        desk: Desk | str,
        agent_ref: str,
        bars: int,
        citations: Citations,
        interval: str = "1h",
        source: str = "",
        task_ref: str | None = None,
        at: dt.datetime | None = None,
    ) -> AuthoredStrategy:
        """Ask the agent for a whole strategy, and write down what it said.

        Every turn is asked against the same material, so an answer cannot be
        conditioned on a number that arrived halfway through. The order the
        slots are asked in is the order the branch structure requires: the
        family first, because the family decides which of the remaining slots
        exist.
        """
        self.turns = []
        the_desk = desk if isinstance(desk, Desk) else Desk(desk)
        moment = at or self._clock.now()
        material = material_for(
            the_desk,
            bars=bars,
            citations=citations,
            interval=interval,
            source=source,
        )

        family_slot = slots_for(None)[0]
        family = self._one(
            self._ask(
                session,
                agent_ref=agent_ref,
                slot=FAMILY,
                question=question_for(family_slot),
                material=material,
                task_ref=task_ref,
            ),
            FAMILY,
        )
        picks: list[tuple[str, str]] = [(FAMILY, family)]
        reasons: dict[str, str] = {FAMILY: self.turns[-1].reasoning}

        for slot in slots_for(family):
            if slot.name == FAMILY:
                continue
            decision = self._ask(
                session,
                agent_ref=agent_ref,
                slot=slot.name,
                question=question_for(slot),
                material=material,
                task_ref=task_ref,
            )
            picks.append((slot.name, self._one(decision, slot.name)))
            reasons[slot.name] = decision.reasoning

        origin_decision = self._ask(
            session,
            agent_ref=agent_ref,
            slot="origin",
            question=origin_question(citations),
            material=material,
            task_ref=task_ref,
        )
        origin = Origin(self._one(origin_decision, "origin"))
        origin_ref = dict(citations.available())[origin]

        weakness_decision = self._ask(
            session,
            agent_ref=agent_ref,
            slot="weakness",
            question=weakness_question(),
            material=material,
            task_ref=task_ref,
        )
        if weakness_decision.abstained:
            raise AuthoringRefused(
                "weakness",
                ValueError(
                    "the agent named no weakness. Every composition has a "
                    "regime it does not survive, and one whose author cannot "
                    "name it has not looked"
                ),
            )
        described = {choice.key: choice.describes for choice in WEAKNESSES}
        weaknesses = (
            *(
                f"{key}: {described[key]}"
                for key in sorted(weakness_decision.chosen)
            ),
            # Once, not once per weakness. Repeating one justification against
            # each of two answers reads as two reasons where the agent gave one.
            f"the author's reasoning: {weakness_decision.reasoning}",
        )

        design = Design(tuple(picks))
        spec = render(
            design, desk=the_desk, bars=bars, interval=interval, source=source
        )

        return self._write(
            session,
            agent_ref=agent_ref,
            desk=the_desk,
            design=design,
            spec=spec,
            reasons=reasons,
            origin=origin,
            origin_ref=origin_ref,
            weaknesses=weaknesses,
            at=moment,
        )

    def revise(
        self,
        session: Session,
        *,
        previous: AuthoredStrategy,
        design: Design,
        slot_name: str,
        key: str,
        reason: str,
        at: dt.datetime | None = None,
    ) -> AuthoredStrategy:
        """Swap one component for another, producing a new version.

        The replacement carries ``Origin.REFINED`` citing the component it
        replaces, which is what that origin is for -- and it means the campaign
        shows up in the novelty count as refinement rather than invention. A
        revision recorded as newly invented would let the company inflate what
        it created by changing one number five times.

        Always a new version, never an edit. The lineage has to be able to say
        how the company got here, and an edited version is a list of things
        that are no longer true.
        """
        moment = at or self._clock.now()
        slot = _slot(slot_name, previous.design.family)
        parent = next(
            component
            for component in previous.components
            if component.spec.get("slot") == slot_name
        )
        replacement = self._synthesis.author_component(
            session,
            kind=slot.kind,
            name=f"{previous.desk.value}.{slot_name}.{key}",
            spec=component_spec(slot, key),
            rationale=(
                f"Revised {slot_name} from {previous.design.get(slot_name)} to "
                f"{key}: {reason.strip()}"
            ),
            origin=Origin.REFINED,
            origin_ref=parent.ref,
            author=previous.agent_ref,
            desk=previous.desk,
            assumes=_assumes(slot_name, key),
            at=moment,
        )
        composition = self._synthesis.mutate(
            session,
            version_ref=previous.version_ref,
            replace=parent,
            with_component=replacement,
            author=previous.agent_ref,
            reason=reason.strip() or "revised inside a declared campaign budget",
            at=moment,
        )
        components = self._synthesis.components_of(session, composition.version.ref)
        return AuthoredStrategy(
            agent_ref=previous.agent_ref,
            desk=previous.desk,
            strategy_ref=previous.strategy_ref,
            version_ref=composition.version.ref,
            design=design,
            spec=render(
                design,
                desk=previous.desk,
                bars=previous.spec.data.bars,
                interval=previous.spec.data.interval,
            ),
            origin=Origin.REFINED,
            origin_ref=parent.ref,
            weaknesses=previous.weaknesses,
            components=components,
            turns=tuple(self.turns),
            novelty=self._synthesis.novelty(session, composition.version.ref),
        )

    def _write(
        self,
        session: Session,
        *,
        agent_ref: str,
        desk: Desk,
        design: Design,
        spec: ExperimentSpec,
        reasons: dict[str, str],
        origin: Origin,
        origin_ref: str,
        weaknesses: tuple[str, ...],
        at: dt.datetime,
    ) -> AuthoredStrategy:
        """Turn the answers into components and a version.

        The rationale on every component is the agent's own ``BECAUSE`` for
        that slot, padded with the choice it justifies so the sentence stands
        alone when somebody reads the component years later without the
        question in front of them.
        """
        components: list[Component] = []
        for slot_name, key in design.picks:
            slot = _slot(slot_name, design.family)
            components.append(
                self._synthesis.author_component(
                    session,
                    kind=slot.kind,
                    name=f"{desk.value}.{slot_name}.{key}",
                    spec=component_spec(slot, key),
                    rationale=(
                        f"Chose {key} for {slot_name}: "
                        f"{reasons.get(slot_name, '').strip()}"
                    ),
                    origin=origin,
                    origin_ref=origin_ref,
                    author=agent_ref,
                    desk=desk,
                    assumes=_assumes(slot_name, key),
                    at=at,
                )
            )

        costs = costs_for(desk)
        strategy = self._synthesis.open_strategy(
            session,
            name=f"{desk.value}-{design.family}-{design.digest()[:8]}",
            thesis=(
                f"{reasons.get(FAMILY, '').strip()} "
                f"Designed as {design.describe()} on the {desk.value} desk, "
                f"paying {costs.round_trip_bps} bps a round trip."
            ),
            desk=desk,
            owner=agent_ref,
            at=at,
        )
        composition = self._synthesis.compose(
            session,
            strategy_ref=strategy.ref,
            components=tuple(components),
            universe={
                "desk": desk.value,
                "selection": spec.universe.selection,
                "point_in_time": spec.universe.point_in_time,
            },
            cost_model={
                "fee_bps": str(spec.backtest.costs.fee_bps),
                "spread_bps": str(spec.backtest.costs.spread_bps),
                "slippage_bps": str(spec.backtest.costs.slippage_bps),
                "set_by": "desk",
            },
            known_weaknesses=weaknesses,
            author=agent_ref,
            constraints={"warmup_bars": spec.backtest.warmup_bars},
            risk_assumptions=(
                "Sizing is whole-position; the engine holds one unit of "
                "exposure or none. Leverage is not a choice this surface offers."
            ),
            change_reason="authored by an agent from the closed design space",
            at=at,
        )

        return AuthoredStrategy(
            agent_ref=agent_ref,
            desk=desk,
            strategy_ref=strategy.ref,
            version_ref=composition.version.ref,
            design=design,
            spec=spec,
            origin=origin,
            origin_ref=origin_ref,
            weaknesses=weaknesses,
            components=tuple(components),
            turns=tuple(self.turns),
            novelty=self._synthesis.novelty(session, composition.version.ref),
        )


def _slot(name: str, family: str) -> Slot:
    for slot in slots_for(family):
        if slot.name == name:
            return slot
    raise KeyError(f"{name} is not a slot on the {family} branch")


def _assumes(slot_name: str, key: str) -> tuple[str, ...]:
    """What a choice quietly requires of a market.

    Implied by the choice rather than asserted by the agent, because an
    assumption is a fact about what the rule needs, not an opinion about it.
    Taking the other side requires a market where the other side can be taken,
    and declaring it here is what makes the portability matrix downgrade the
    desks where it cannot.
    """
    if slot_name == "direction" and key == "long_short":
        return (Assumption.SHORT_SELLING.value,)
    return ()

