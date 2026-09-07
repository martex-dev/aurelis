"""An agent in the seat the playbook used to occupy.

M10 scored a **procedure**: a set of numeric thresholds over the closed defect
taxonomy, applied to the mechanical tests the Chair dispatches. It said, in as
many words, that the harness would not change when agents reasoned for
themselves — the playbook would simply be replaced by the agent, and the same
twelve worlds would mark the same twelve answers.

This is that replacement.

An :class:`AgentCritic` is handed exactly what a playbook is handed: the
presented specification, the headline metric on the one draw a critic gets, and
the result of every applicable mechanical test. What it does with them is
different. A playbook compares each number to a threshold. An agent is asked a
question with a closed answer set and has to pick.

Three things travel unchanged from M10, deliberately:

**The evidence.** The same runs, from the same bench, on the same draw. An
agent shown different material would be scored on a different question.

**The marking.** :func:`aurelis.training.scoring.mark` against measured truth,
with `UNDETERMINED` items excluded. The agent is not graded against the
catalogue's *intent* any more than the playbook was.

**The refusals.** An answer outside the taxonomy is an error, not a shrug; a
justification citing a figure the agent was not shown is an error too. Both are
counted, and a critic that errors on a scenario **catches nothing there** —
which is the honest scoring, because a review nobody could act on is not a
review.

What sits behind the seat in CI is the mock provider, as everywhere else here.
The mechanism is real and the reasoner in a test is scripted; point the runtime
at a real provider and the same path asks a real model.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.agents.decide import (
    Choice,
    Decision,
    Question,
    UndecidableAnswer,
    decide_as,
)
from aurelis.agents.interpret import UnsourcedFigures
from aurelis.core.enums import ModelTier
from aurelis.engines.synthetic.scenarios import Scenario
from aurelis.engines.synthetic.truth import Bench, varied_spec
from aurelis.meetings.taxonomy import LOWER_IS_BETTER, MARKET_DEFECTS, DefectKind
from aurelis.meetings.types import ObjectionType
from aurelis.training.critique import CRITIC_SEED, Critique
from aurelis.training.playbook import Playbook

__all__ = ["CRITIC_SYSTEM", "AgentCritic", "AgentTurn", "critique_question"]

CRITIC_SYSTEM = (
    "You are a research critic in a quantitative company. You are shown one "
    "backtest and the result of re-running it with exactly one thing varied. "
    "Your job is to say which of a closed list of defects the evidence "
    "supports, and to say nothing else.\n\n"
    "Rules you are held to:\n"
    "- Name only options from the list. Anything else is discarded.\n"
    "- Cite figures exactly as they appear above; see the rule stated with "
    "the question. A number from anywhere else invalidates your answer.\n"
    "- `nothing` is a real answer and is often the right one. A critic that "
    "finds a defect every time is worth less than no critic.\n"
    "- A stress test settles nothing against a specification that never "
    "showed a result. If the rule did not make money, it did not fail to "
    "survive anything."
)


@dataclass(frozen=True, slots=True)
class AgentTurn:
    """One scenario, as the agent saw it and answered it."""

    scenario_id: str
    material: dict[str, Any]
    decision: Decision | None
    error: str = ""

    @property
    def refused(self) -> bool:
        return self.decision is None

    def as_payload(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "decision": self.decision.as_payload() if self.decision else None,
            "error": self.error,
        }


def critique_question(applicable: tuple[ObjectionType, ...]) -> Question:
    """The question, carrying only the defects that apply to this spec.

    Filtered rather than offered wholesale, exactly as
    :func:`aurelis.meetings.taxonomy.defects_for` filters what a Critic may
    allege in a live meeting: an objection that cannot apply is noise, and
    noise is what stops real objections being read.
    """
    return Question(
        prompt=(
            "Which defects does this evidence support alleging against the "
            "specification?"
        ),
        options=tuple(
            Choice(
                key=defect.value,
                describes=(
                    f"{MARKET_DEFECTS[defect].asks} "
                    f"(the test varies {MARKET_DEFECTS[defect].varies}; "
                    f"a {MARKET_DEFECTS[defect].kind.value} test)"
                ),
            )
            for defect in applicable
        ),
        multiple=True,
    )


class AgentCritic:
    """A critic that decides, rather than a procedure that compares.

    Interface-compatible with a :class:`~aurelis.training.playbook.Playbook`
    where the suite needs it — ``describe`` and ``covers`` — so it can be run
    through :class:`~aurelis.training.suite.TrainingSuite` unchanged.
    """

    __slots__ = (
        "agent_ref",
        "provider",
        "session",
        "specialty",
        "tier",
        "turns",
        "errors",
    )

    def __init__(
        self,
        provider: Any,
        session: Any,
        *,
        agent_ref: str,
        specialty: frozenset[ObjectionType],
        tier: ModelTier = ModelTier.MID,
    ) -> None:
        self.provider = provider
        self.session = session
        self.agent_ref = agent_ref
        self.specialty = specialty
        self.tier = tier
        """Which model answers. The agent's own tier, resolved from its
        charters and passed in by whoever seated it, rather than a constant
        that happened to be right for the Strategy Critic."""
        self.turns: list[AgentTurn] = []
        self.errors: list[str] = []

    # --------------------------------------------- the playbook's own surface

    @property
    def covers(self) -> frozenset[ObjectionType]:
        return self.specialty

    def describe(self) -> str:
        return f"agent:{self.agent_ref}"

    # ------------------------------------------------------------- critiquing

    def critique(self, scen: Scenario, bench: Bench, *, seed: int = CRITIC_SEED) -> Critique:
        """Show the agent one scenario and record what it alleged."""
        presented = scen.presented()
        observed = bench.value(scen, presented, seed=seed)
        worse_is_larger = scen.metric in LOWER_IS_BETTER

        from aurelis.meetings.taxonomy import defects_for

        applicable = tuple(
            d.type for d in defects_for(presented) if d.type in self.specialty
        )
        if not applicable:
            return Critique(
                scenario_id=scen.scenario_id,
                playbook=self.describe(),
                alleged=frozenset(),
                calls_effect_real=False,
                observed=observed,
                considered=frozenset(),
                detail={"note": "no defect in this agent's specialty applies"},
            )

        material = self._material(
            scen, bench, presented, observed, applicable, seed=seed
        )
        question = critique_question(applicable)

        try:
            decision = decide_as(
                self.provider,
                self.session,
                agent_ref=self.agent_ref,
                question=question,
                material=material,
                system=CRITIC_SYSTEM,
                tier=self.tier,
            )
        except (UndecidableAnswer, UnsourcedFigures) as exc:
            # A critique nobody could act on is not a critique. The turn is
            # recorded as a refusal, the agent alleges nothing, and the
            # marking counts every real defect here as missed -- which is the
            # honest cost of an answer that could not be read.
            self.errors.append(f"{scen.scenario_id}: {type(exc).__name__}: {exc}")
            self.turns.append(
                AgentTurn(scen.scenario_id, material, None, f"{type(exc).__name__}")
            )
            return Critique(
                scenario_id=scen.scenario_id,
                playbook=self.describe(),
                alleged=frozenset(),
                calls_effect_real=False,
                observed=observed,
                considered=frozenset(applicable),
                detail={"refused": str(exc)[:200]},
            )

        self.turns.append(AgentTurn(scen.scenario_id, material, decision))
        alleged = frozenset(
            ObjectionType(key) for key in decision.chosen if key in {d.value for d in applicable}
        )
        calls_real = (
            observed < -Decimal("0.01") if worse_is_larger else observed > Decimal("0.01")
        )
        return Critique(
            scenario_id=scen.scenario_id,
            playbook=self.describe(),
            alleged=alleged,
            calls_effect_real=calls_real,
            observed=observed,
            considered=frozenset(applicable),
            detail={"reasoning": decision.reasoning[:300]},
        )

    # --------------------------------------------------------------- material

    def _material(
        self,
        scen: Scenario,
        bench: Bench,
        presented: Any,
        observed: Decimal,
        applicable: tuple[ObjectionType, ...],
        *,
        seed: int,
    ) -> dict[str, Any]:
        """Exactly what a playbook is given, rendered for a reader.

        Every number here comes from a run. Nothing is computed for the
        prompt that is not also what the threshold procedure compares, so the
        agent and the playbook are answering the same question about the same
        evidence.
        """
        worse_is_larger = scen.metric in LOWER_IS_BETTER
        tests: dict[str, str] = {}
        for defect in applicable:
            varied = varied_spec(scen, defect, observed)
            under_test = bench.value(scen, varied, seed=seed)
            degradation = (
                under_test - observed if worse_is_larger else observed - under_test
            )
            kind = MARKET_DEFECTS[defect].kind
            tests[defect.value] = (
                f"varied run {scen.metric} = {under_test}; "
                f"change against the original = {degradation}; "
                f"this is a {kind.value} test"
                + (
                    " (the varied run is the truer one)"
                    if kind is DefectKind.CORRECTIVE
                    else " (a what-if; the question is whether a result survives it)"
                )
            )
        return {
            "the_specification": {
                "signal": presented.signal.kind,
                "lookback": presented.signal.lookback,
                "universe_basis": presented.universe.selection,
                "bars": presented.data.bars,
                "round_trip_cost_bps": str(presented.backtest.costs.round_trip_bps),
            },
            "as_reported": {
                scen.metric: str(observed),
                "note": (
                    "this is one draw of history, which is all a researcher "
                    "ever has"
                ),
            },
            "mechanical_tests": tests,
        }


def as_playbook_result(critic: AgentCritic) -> dict[str, Any]:
    """What the critic did across a whole suite, for the record."""
    return {
        "agent": critic.agent_ref,
        "specialty": sorted(d.value for d in critic.specialty),
        "turns": [t.as_payload() for t in critic.turns],
        "errors": list(critic.errors),
        "refusals": sum(1 for t in critic.turns if t.refused),
    }


def playbook_shaped(critic: AgentCritic) -> Playbook | AgentCritic:
    """The critic, where a playbook is expected. Present for readability."""
    return critic
