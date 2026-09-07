"""The demonstration: an agent in the critic's seat, weighed against the procedure.

.. code-block:: text

    the shipped playbook   over twelve worlds   caught 7/8, 1 false alarm
    an agent in the seat   the same worlds      caught 8/8, 8 false alarms
    the company's own gate                      REFUSED

That last line is the point, and it is not a disappointment. The agent caught
**everything the suite plants**, including the one defect the procedure missed —
and raised an objection on eight specifications that did not have one. The
regression gate M10 built compares on counts and refuses a revision that raises
more false alarms, so it refuses this one. The company declined to promote a
critic that finds more, because finding more is not the same as being better,
and it declined on arithmetic rather than on taste.

**What is behind the seat here is not a model.** Every model call in this
repository runs against the mock provider, and a mock that echoes its input
cannot answer a multiple-choice question — so
:mod:`aurelis.training.standin` supplies a deterministic function of the prompt
to sit in the chair. What that exercises is the machinery: the closed option
set, the parse, the figure check, the refusal path, the scoring against
measured truth, and the gate. Point the runtime at a real provider and the same
code path asks a real model; nothing else changes, and the numbers below would
be that model's.

So the honest claim is narrow and worth making: **the seat exists, it is shut,
and what sits in it is judged by the same instrument as the procedure it would
replace.**
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from aurelis.meetings.taxonomy import MARKET_DEFECTS
from aurelis.meetings.types import ObjectionType
from aurelis.training.critic import AgentCritic
from aurelis.training.playbook import INCUMBENT, Playbook
from aurelis.training.scoring import Scorecard
from aurelis.training.suite import SuiteResult, TrainingSuite

__all__ = ["SeatingOutcome", "run_seating"]


@dataclass(frozen=True, slots=True)
class SeatingOutcome:
    """What putting an agent in the seat established."""

    procedure: SuiteResult
    agent: SuiteResult
    agent_ref: str
    refusals: int
    errors: tuple[str, ...]
    ships: bool
    verdict: str
    detail: str

    @property
    def caught_more(self) -> bool:
        return self.agent.score.caught > self.procedure.score.caught

    @property
    def alarmed_more(self) -> bool:
        return self.agent.score.false_alarms > self.procedure.score.false_alarms

    def describe(self) -> str:
        return (
            f"procedure {self.procedure.score.describe()}; "
            f"agent {self.agent.score.describe()}; "
            f"{'ships' if self.ships else 'REFUSED'} — {self.detail}"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "agent": self.agent_ref,
            "procedure_score": self.procedure.score.as_payload(),
            "agent_score": self.agent.score.as_payload(),
            "refusals": self.refusals,
            "errors": list(self.errors),
            "ships": self.ships,
            "verdict": self.verdict,
            "detail": self.detail,
            "caveat": (
                "The reasoner behind the seat in this repository is a "
                "deterministic stand-in, not a model. What is demonstrated is "
                "the harness around it."
            ),
        }


def _weigh(procedure: Scorecard, agent: Scorecard) -> tuple[bool, str, str]:
    """The same rule the playbook regression gate applies, on counts.

    Counts rather than rates, for the reason M10 gave: a critic that narrowed
    what it looked at could keep a perfect catch rate while finding less.
    """
    caught = agent.caught - procedure.caught
    alarms = agent.false_alarms - procedure.false_alarms
    detail = (
        f"caught {procedure.caught} -> {agent.caught}, "
        f"false alarms {procedure.false_alarms} -> {agent.false_alarms}"
    )
    if caught >= 0 and alarms <= 0:
        return True, "agent_better", detail
    if caught <= 0 and alarms >= 0:
        return False, "procedure_better", detail
    return (
        False,
        "mixed",
        detail
        + " — it finds more and cries wolf more. Which is better is a policy "
        "question, and the gate refuses rather than deciding one.",
    )


def run_seating(
    runtime: Any,
    *,
    agent_handle: str = "CRITIC",
    base: Playbook = INCUMBENT,
    specialty: frozenset[ObjectionType] | None = None,
    at: dt.datetime | None = None,
) -> SeatingOutcome:
    """Run the procedure and an agent over the same suite, and weigh them.

    ``specialty`` restricts **both** sides. A comparison where one of them
    faced more questions than the other would not be a comparison -- it would
    be a report that the wider remit found more, which is arithmetic rather
    than evidence.
    """
    suite: TrainingSuite = runtime.training
    specialty = specialty if specialty is not None else frozenset(MARKET_DEFECTS)
    procedure = suite.run(base.restricted_to(specialty))

    with runtime.database.session() as session:
        seated = runtime.roster.by_handle(session, agent_handle)
        agent_ref = seated.ref
        critic = AgentCritic(
            runtime.provider,
            session,
            agent_ref=agent_ref,
            specialty=specialty,
            # Resolved from the charters this agent covers, not chosen here.
            # `resolve_authority` has computed it since M1; until M17 nothing
            # downstream used it.
            tier=seated.authority.tier,
        )
        result = suite.run_agent(critic)

    ships, verdict, detail = _weigh(procedure.score, result.score)
    return SeatingOutcome(
        procedure=procedure,
        agent=result,
        agent_ref=agent_ref,
        refusals=sum(1 for turn in critic.turns if turn.refused),
        errors=tuple(critic.errors),
        ships=ships,
        verdict=verdict,
        detail=detail,
    )


def specialty_of_everything() -> frozenset[ObjectionType]:
    """Every defect in the taxonomy. What a generalist critic is asked."""
    return frozenset(MARKET_DEFECTS)
