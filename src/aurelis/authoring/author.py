"""The author's seat: an agent writes the rule, and the rule is the strategy.

M15 put an agent in this seat with a menu of 72 designs and called the pick a
strategy. The brief for this stage says why a menu can never hold an idea only
the agent would have had, and says the menu has to go. It is gone. What sits
here now is an agent **writing a rule** in the company's rule language
(:mod:`aurelis.rules`), in its own words, with a cited origin — and the
company preregistering the rule before anything is measured.

One model call writes the rule; a second, closed question asks where it came
from. Four refusals hold the seat shut.

**A rule that does not parse is not a rule.** The language is small and the
parser refuses rather than guesses. A near-miss repaired by the software would
put the software's rule on the agent's record.

**The rationale is figure-checked.** Every numeral in it must appear in the
material or in the rule itself. The numbers inside the rule are the agent's to
choose — choosing them is the job — and the rationale may cite them; what it
may not do is reason from a number nobody gave it and it did not write.

**A rule with no origin is not authored.** :class:`~aurelis.strategy.states.Origin`
is the field the company's claim to have *created* anything rests on, and an
uncited creation is unfalsifiable.

**A rule whose author cannot name a weakness is refused**, which is M8's rule:
every strategy has a regime it does not survive, and an author who cannot say
which has not looked.

What the agent is shown is structure only — the desk, its costs, the budget
in bars, prior work, and the language. Never a measurement of the data the
rule will be scored on. An author shown this quarter's Sharpe for a few
candidate rules would be selecting, not authoring.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from aurelis.agents.decide import Choice, Decision, Question, decide_as
from aurelis.agents.interpret import (
    FIGURE_RULE,
    UnsourcedFigures,
    allowed_figures,
    render_material,
    unsourced_numerals,
)
from aurelis.authoring.specs import render_spec
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import ModelTier
from aurelis.desks.calendars import calendar_for
from aurelis.desks.costs import costs_for
from aurelis.engines.spec import ExperimentSpec
from aurelis.org.desks import DESKS, Desk
from aurelis.platform.llm.routing import model_for
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef
from aurelis.rules.language import REFERENCE, Program, RuleSyntaxError, parse
from aurelis.strategy.markets import Assumption
from aurelis.strategy.states import ComponentKind, Origin
from aurelis.strategy.synthesis import Novelty, Synthesis
from aurelis.strategy.tables import Component

__all__ = [
    "MATERIAL_SECTIONS",
    "RULE_FORM",
    "SYSTEM",
    "AuthorTurn",
    "AuthoredStrategy",
    "Authoring",
    "AuthoringRefused",
    "Citations",
    "StrategyAuthor",
    "material_for",
    "origin_question",
    "parse_authoring",
]

SYSTEM = (
    "You are a strategy architect at a quantitative research company. You are "
    "writing one trading rule, in a small fixed language, for one market desk. "
    "The company will then preregister your rule, measure it against criteria "
    "fixed before the run, and refute it if the evidence says so.\n\n"
    "Writing a rule is NOT a claim that it works. It is choosing what to test "
    "next. The data available is described below and may be short or "
    "synthetic; that is a fact about this experiment, not a reason to decline "
    "to write one. Reserve `nothing` for when no rule could be tested at all, "
    "not for when you are uncertain whether it will succeed.\n\n"
    "You do not choose the costs, the universe or the window; those belong to "
    "the desk. Everything else about the rule is yours."
)

RULE_FORM = (
    "Write one rule in the language described above. Reply in exactly this "
    "form and nothing else:\n"
    "RULE:\n"
    "<one clause per line>\n"
    "RATIONALE: <why this rule should earn its costs on this desk, one to "
    "three sentences>\n"
    "WEAKNESS: <the regime it will not survive, one sentence>\n\n"
    "Or, if no rule could be tested at all: RULE: nothing\n\n"
    "The numbers inside RULE are yours to choose. RATIONALE and WEAKNESS may "
    f"cite them and the figures above, and nothing else. {FIGURE_RULE}"
)
"""The reply form. Its digits are the material's digits, so appending it
cannot widen what a rationale may cite."""

MATERIAL_SECTIONS: tuple[str, ...] = ("desk", "costs", "budget", "prior_work", "the_language")
"""Everything the author is shown, and nothing else. None of it is a result."""

_SECTION = re.compile(r"^\s*(RULE|RATIONALE|WEAKNESS)\s*:\s*(.*)$", re.I)


@dataclass(frozen=True, slots=True)
class Citations:
    """What the agent may claim its work came from.

    Each entry is a reference that already exists in the company's record. The
    agent chooses *which* provenance applies; it cannot write the citation
    itself, because a free-text origin is exactly the unfalsifiable claim
    :mod:`aurelis.strategy.synthesis` refuses.
    """

    task_ref: str | None = None
    failure_ref: str | None = None
    corpus_ref: str | None = None

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
    """The agent did not produce a rule, so nothing was written."""

    def __init__(self, slot: str, cause: Exception | str) -> None:
        super().__init__(
            f"authoring refused at {slot!r}: {cause}. A half-authored strategy "
            "would be finished by the software and recorded as the agent's "
            "design, so nothing is written."
        )
        self.slot = slot
        self.cause = cause


@dataclass(frozen=True, slots=True)
class AuthorTurn:
    """One exchange with the seat, and what came back."""

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
class Authoring:
    """What the agent wrote, parsed and not interpreted."""

    program: Program | None
    rationale: str
    weakness: str

    @property
    def declined(self) -> bool:
        return self.program is None


def parse_authoring(text: str, *, require_weakness: bool = True) -> Authoring:
    """The three sections out of a reply, or a refusal that says which failed."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _SECTION.match(line)
        if match:
            current = match.group(1).upper()
            sections[current] = [match.group(2).strip()] if match.group(2).strip() else []
        elif current is not None and line.strip():
            sections[current].append(line.rstrip())
    rule_lines = sections.get("RULE")
    if rule_lines is None:
        raise AuthoringRefused("rule", "the reply has no RULE section")
    rule_text = "\n".join(rule_lines).strip()
    if rule_text.lower() == "nothing":
        return Authoring(None, "", "")
    try:
        program = parse(rule_text)
    except RuleSyntaxError as error:
        raise AuthoringRefused("rule", error) from error
    rationale = " ".join(sections.get("RATIONALE", [])).strip()
    weakness = " ".join(sections.get("WEAKNESS", [])).strip()
    if len(rationale) <= 20:
        raise AuthoringRefused(
            "rationale", "a rationale of fewer than twenty characters is not one"
        )
    if require_weakness and len(weakness) <= 10:
        raise AuthoringRefused(
            "weakness",
            "the agent named no weakness. Every rule has a regime it does not "
            "survive, and one whose author cannot name it has not looked",
        )
    return Authoring(program, rationale, weakness)


@dataclass(frozen=True, slots=True)
class AuthoredStrategy:
    """A rule an agent wrote, and the record of it writing it."""

    agent_ref: str
    desk: Desk
    strategy_ref: str
    version_ref: str
    program: Program
    spec: ExperimentSpec
    origin: Origin
    origin_ref: str
    rationale: str
    weaknesses: tuple[str, ...]
    components: tuple[Component, ...] = field(default=())
    turns: tuple[AuthorTurn, ...] = field(default=())
    novelty: Novelty | None = None

    @property
    def rule(self) -> str:
        return self.program.text

    def describe(self) -> str:
        return (
            f"{self.agent_ref} authored {self.version_ref} on {self.desk.value}: "
            f"{self.program.text.replace(chr(10), ' | ')}"
        )

    def design_payload(self) -> dict[str, Any]:
        """What the attempt row records. ``rule`` is the canonical text and
        ``program`` the structure it hashes from."""
        return {"rule": self.program.text, "program": self.program.payload}

    def as_payload(self) -> dict[str, Any]:
        return {
            "agent": self.agent_ref,
            "desk": self.desk.value,
            "strategy": self.strategy_ref,
            "version": self.version_ref,
            "rule": self.program.text,
            "rule_digest": self.program.digest,
            "spec_digest": self.spec.digest(),
            "origin": self.origin.value,
            "origin_ref": self.origin_ref,
            "weaknesses": list(self.weaknesses),
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
    the rule will be scored on, so the rule cannot have been chosen for fitting
    it.
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
            "data": (
                f"recorded market data: {source}" if source else "fixture, not live market data"
            ),
            "instruments": "one instrument per run; the rule sees its closes only",
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
        "the_language": {
            "reference": REFERENCE,
            "example of the syntax": "ret(24) > 0.02 -> long",
        },
    }


def origin_question(citations: Citations) -> Question:
    """Where did this come from? Closed, and abstention is refused."""
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
    return Question(prompt="Where did this rule come from?", options=options, multiple=False)


class StrategyAuthor:
    """Drives an agent through writing a rule and records what it wrote."""

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
        self.turns: list[AuthorTurn] = []

    # ------------------------------------------------------------- asking

    def write_rule(
        self,
        session: Session,
        *,
        agent_ref: str,
        material: dict[str, Any],
        form: str = RULE_FORM,
        task_ref: str | None = None,
        require_weakness: bool = True,
    ) -> Authoring:
        """One call: the rule, the rationale, the weakness. Refuse anything else.

        Public because a revision is the same seat writing a different rule,
        and a campaign that reimplemented the ask would have its own parse, its
        own figure check and its own idea of what a refusal is.
        """
        rendered = f"{render_material(material)}\n\n{form}"
        model_id = model_for(self._provider.name, self.tier)
        response = self._provider.complete(
            session,
            LlmRequest(
                model=ModelRef(
                    provider=self._provider.name, model=model_id, tier=self.tier, max_tokens=600
                ),
                system=SYSTEM,
                messages=(Message("user", rendered),),
                actor=agent_ref,
                task_ref=task_ref,
            ),
        )
        try:
            authoring = parse_authoring(response.text, require_weakness=require_weakness)
        except AuthoringRefused as error:
            self.turns.append(
                AuthorTurn(
                    slot=error.slot, chosen=(), reasoning="", refused=True, error=str(error.cause)
                )
            )
            raise
        if authoring.declined:
            self.turns.append(
                AuthorTurn(slot="rule", chosen=(), reasoning="", refused=True, error="declined")
            )
            raise AuthoringRefused(
                "rule",
                "the agent declined to write a rule. A software default recorded "
                "as the agent's rule would make the strategy the company's and "
                "the record the agent's",
            )
        assert authoring.program is not None
        permitted = allowed_figures(material, {"rule": authoring.program.source, "form": form})
        invented = unsourced_numerals(f"{authoring.rationale}\n{authoring.weakness}", permitted)
        if invented:
            unsourced = UnsourcedFigures(invented, len(permitted))
            self.turns.append(
                AuthorTurn(
                    slot="rationale", chosen=(), reasoning="", refused=True, error=str(unsourced)
                )
            )
            raise AuthoringRefused("rationale", unsourced) from unsourced
        self.turns.append(
            AuthorTurn(
                slot="rule",
                chosen=(authoring.program.digest[:12],),
                reasoning=authoring.rationale,
            )
        )
        return authoring

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
                slot=slot, chosen=tuple(sorted(decision.chosen)), reasoning=decision.reasoning
            )
        )
        return decision

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
        """Ask the agent for a rule, then where it came from, and write it down."""
        self.turns = []
        the_desk = desk if isinstance(desk, Desk) else Desk(desk)
        moment = at or self._clock.now()
        material = material_for(
            the_desk, bars=bars, citations=citations, interval=interval, source=source
        )

        authoring = self.write_rule(
            session, agent_ref=agent_ref, material=material, task_ref=task_ref
        )
        assert authoring.program is not None

        origin_decision = self._ask(
            session,
            agent_ref=agent_ref,
            slot="origin",
            question=origin_question(citations),
            material=material,
            task_ref=task_ref,
        )
        if origin_decision.abstained:
            raise AuthoringRefused(
                "origin",
                "the agent abstained on provenance, which has no default; an "
                "uncited origin makes the claim to have created this unfalsifiable",
            )
        origin = Origin(next(iter(origin_decision.chosen)))
        origin_ref = dict(citations.available())[origin]

        spec = render_spec(
            authoring.program, desk=the_desk, bars=bars, interval=interval, source=source
        )
        return self._write(
            session,
            agent_ref=agent_ref,
            desk=the_desk,
            program=authoring.program,
            spec=spec,
            rationale=authoring.rationale,
            origin=origin,
            origin_ref=origin_ref,
            weaknesses=(authoring.weakness,),
            at=moment,
        )

    def revise(
        self,
        session: Session,
        *,
        previous: AuthoredStrategy,
        program: Program,
        rationale: str,
        at: dt.datetime | None = None,
    ) -> AuthoredStrategy:
        """Replace the rule with a new one, producing a new version.

        The replacement carries ``Origin.REFINED`` citing the component it
        replaces, so the campaign shows in the novelty count as refinement
        rather than invention. Always a new version, never an edit.
        """
        moment = at or self._clock.now()
        parent = next(
            component
            for component in previous.components
            if component.kind == ComponentKind.SIGNAL.value
        )
        replacement = self._synthesis.author_component(
            session,
            kind=ComponentKind.SIGNAL,
            name=f"{previous.desk.value}.rule.{program.digest[:8]}",
            spec=_component_spec(program),
            rationale=f"Revised the rule: {rationale.strip()}",
            origin=Origin.REFINED,
            origin_ref=parent.ref,
            author=previous.agent_ref,
            desk=previous.desk,
            assumes=_assumes(program),
            at=moment,
        )
        composition = self._synthesis.mutate(
            session,
            version_ref=previous.version_ref,
            replace=parent,
            with_component=replacement,
            author=previous.agent_ref,
            reason=rationale.strip() or "revised inside a declared campaign budget",
            at=moment,
        )
        components = self._synthesis.components_of(session, composition.version.ref)
        return AuthoredStrategy(
            agent_ref=previous.agent_ref,
            desk=previous.desk,
            strategy_ref=previous.strategy_ref,
            version_ref=composition.version.ref,
            program=program,
            spec=render_spec(
                program,
                desk=previous.desk,
                bars=previous.spec.data.bars,
                interval=previous.spec.data.interval,
                source=previous.spec.data.source
                if not previous.spec.data.source.startswith("fixture:")
                else "",
            ),
            origin=Origin.REFINED,
            origin_ref=parent.ref,
            rationale=rationale,
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
        program: Program,
        spec: ExperimentSpec,
        rationale: str,
        origin: Origin,
        origin_ref: str,
        weaknesses: tuple[str, ...],
        at: dt.datetime,
    ) -> AuthoredStrategy:
        component = self._synthesis.author_component(
            session,
            kind=ComponentKind.SIGNAL,
            name=f"{desk.value}.rule.{program.digest[:8]}",
            spec=_component_spec(program),
            rationale=rationale,
            origin=origin,
            origin_ref=origin_ref,
            author=agent_ref,
            desk=desk,
            assumes=_assumes(program),
            at=at,
        )
        costs = costs_for(desk)
        strategy = self._synthesis.open_strategy(
            session,
            name=f"{desk.value}-rule-{program.digest[:8]}",
            thesis=(
                f"{rationale.strip()} Rule: {program.text.replace(chr(10), ' | ')}. "
                f"On the {desk.value} desk, paying {costs.round_trip_bps} bps a round trip."
            ),
            desk=desk,
            owner=agent_ref,
            at=at,
        )
        composition = self._synthesis.compose(
            session,
            strategy_ref=strategy.ref,
            components=(component,),
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
                "exposure, its negative, or none. Leverage is not a choice this "
                "surface offers."
            ),
            change_reason="authored by an agent as a rule in the company's rule language",
            at=at,
        )
        return AuthoredStrategy(
            agent_ref=agent_ref,
            desk=desk,
            strategy_ref=strategy.ref,
            version_ref=composition.version.ref,
            program=program,
            spec=spec,
            origin=origin,
            origin_ref=origin_ref,
            rationale=rationale,
            weaknesses=weaknesses,
            components=(component,),
            turns=tuple(self.turns),
            novelty=self._synthesis.novelty(session, composition.version.ref),
        )


def _component_spec(program: Program) -> dict[str, Any]:
    """What the component records: the program, and what a reader needs to
    know without holding the language module in their head."""
    return {
        "language": "aurelis.rules",
        "program": program.payload,
        "text": program.text,
        "as_written": program.source,
        "warmup": program.warmup,
        "uses_short": program.uses_short,
        "digest": program.digest,
    }


def _assumes(program: Program) -> tuple[str, ...]:
    """What a rule quietly requires of a market. Implied, not asserted."""
    return (Assumption.SHORT_SELLING.value,) if program.uses_short else ()
