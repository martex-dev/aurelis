"""Onboarding: an agent's starting record is its scenario performance.

Before M10 ``onboard_all`` was a state change with a docstring apologising for
being one. Now a newly hired agent runs the suite for its specialty, the result
is written down, and **a failure blocks activation in the database** — not in
this module, which could be bypassed, but in a trigger on the ``agents`` table
(:mod:`aurelis.training.triggers`).

Three verdicts, and the third matters as much as the other two:

``PASSED``     scored against the standard and clear of it
``FAILED``     scored and short of it. Does not start work.
``NOT_SCORED`` the suite had no fair question. **Not a pass.**

Most of the launch roster lands on the third. A Company Manager has no planted
defect to catch, and a specialty with only two settled questions in the whole
catalogue is too thin to certify anybody on. Saying so is the honest report;
inventing a specialty for every charter so that nobody has a blank record would
be fiction in the permanent record of two thirds of the company.

What is being scored today is the **procedure a charter issues**, not the
agent's own judgement — agents do not yet reason their way through a critique.
Every report says so. The harness does not change when they do: the playbook is
replaced by the agent, and the same twelve worlds mark the same twelve answers.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent, AgentState
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.engines.synthetic.scenarios import catalogue_digest
from aurelis.meetings.types import ObjectionType
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger
from aurelis.training.playbook import INCUMBENT, Playbook, playbook_for, specialty_of
from aurelis.training.suite import SuiteResult, TrainingSuite
from aurelis.training.tables import ScenarioMark, TrainingRun, TrainingVerdict

__all__ = ["STANDARD", "Onboarding", "Standard", "TrainingOutcome"]


@dataclass(frozen=True, slots=True)
class Standard:
    """The bar an agent must clear to start work.

    Deliberately modest for a first standard, and set from what a review
    actually needs rather than from what the incumbent happens to score. A
    critic that misses more than two in five real defects is worse than no
    critic, because the company would rely on it. One that cries wolf more than
    one time in five makes reviews unreadable, which costs the same thing by a
    slower route.

    ``min_questions`` is the guard against certifying on nothing. A specialty
    with two settled questions in the whole catalogue cannot distinguish a good
    critic from a lucky one, and an agent whose record rests on two questions
    should be marked untested rather than approved.
    """

    min_catch_rate: Decimal = Decimal("0.60")
    max_false_alarm_rate: Decimal = Decimal("0.20")
    min_effect_accuracy: Decimal = Decimal("0.75")
    min_questions: int = 3

    def as_payload(self) -> dict[str, Any]:
        return {
            "min_catch_rate": str(self.min_catch_rate),
            "max_false_alarm_rate": str(self.max_false_alarm_rate),
            "min_effect_accuracy": str(self.min_effect_accuracy),
            "min_questions": self.min_questions,
        }


STANDARD = Standard()


@dataclass(frozen=True, slots=True)
class TrainingOutcome:
    """What onboarding concluded, and why."""

    ref: str
    agent_ref: str
    verdict: TrainingVerdict
    reason: str
    specialty: frozenset[ObjectionType]
    result: SuiteResult | None

    @property
    def may_work(self) -> bool:
        """Whether this record permits the agent to start.

        ``NOT_SCORED`` permits work and certifies nothing. An agent the suite
        could not question is not one it has found wanting, and refusing to
        staff the company because the catalogue has a hole would be the
        measurement making a decision it has no evidence for.
        """
        return self.verdict is not TrainingVerdict.FAILED

    def describe(self) -> str:
        if self.result is None:
            return f"{self.verdict.value}: {self.reason}"
        return f"{self.verdict.value}: {self.result.score.describe()} — {self.reason}"


class Onboarding:
    """Runs the suite for an agent and writes its starting record."""

    __slots__ = ("_suite", "_ledger", "_clock", "_standard")

    def __init__(
        self,
        suite: TrainingSuite | None = None,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
        *,
        standard: Standard = STANDARD,
    ) -> None:
        self._clock = clock or SystemClock()
        self._suite = suite or TrainingSuite()
        self._ledger = ledger or Ledger(self._clock)
        self._standard = standard

    @property
    def suite(self) -> TrainingSuite:
        return self._suite

    @property
    def standard(self) -> Standard:
        return self._standard

    # ------------------------------------------------------------- judging

    def judge(self, result: SuiteResult | None) -> tuple[TrainingVerdict, str]:
        """The verdict rule. Pure, so it can be argued with separately."""
        if result is None:
            return (
                TrainingVerdict.NOT_SCORED,
                "no charter this agent holds has a scenario specialty",
            )
        score = result.score
        if score.planted < self._standard.min_questions:
            return (
                TrainingVerdict.NOT_SCORED,
                f"only {score.planted} settled question(s) in this specialty; "
                f"{self._standard.min_questions} are needed to certify anyone",
            )
        failures: list[str] = []
        catch = score.catch_rate
        if catch is not None and catch < self._standard.min_catch_rate:
            failures.append(
                f"caught {score.caught}/{score.planted} "
                f"({catch}) against {self._standard.min_catch_rate}"
            )
        alarms = score.false_alarm_rate
        if alarms is not None and alarms > self._standard.max_false_alarm_rate:
            failures.append(
                f"false alarms {alarms} against {self._standard.max_false_alarm_rate}"
            )
        accuracy = score.effect_accuracy
        if accuracy is not None and accuracy < self._standard.min_effect_accuracy:
            failures.append(
                f"effect calls {accuracy} against {self._standard.min_effect_accuracy}"
            )
        if failures:
            return TrainingVerdict.FAILED, "; ".join(failures)
        return (
            TrainingVerdict.PASSED,
            f"caught {score.caught}/{score.planted}, "
            f"{score.false_alarms} false alarm(s) in "
            f"{score.false_alarms + score.true_silences}",
        )

    # -------------------------------------------------------------- running

    def run(
        self,
        session: Session,
        agent_ref: str,
        *,
        playbook: Playbook | None = None,
        at: dt.datetime | None = None,
    ) -> TrainingOutcome:
        """Score one agent and record the result.

        ``playbook`` overrides the procedure its charters would issue. That is
        how a weaker procedure can be put in front of the same twelve worlds
        and refused, which is the only way to know the gate does anything.
        """
        moment = at or self._clock.now()
        coverage = self._coverage(session, agent_ref)
        specialty = specialty_of(coverage)
        issued = playbook if playbook is not None else playbook_for(coverage)
        if issued is not None and playbook is not None:
            issued = issued.restricted_to(specialty) if specialty else issued

        result = self._suite.run(issued) if issued is not None else None
        verdict, reason = self.judge(result)

        ref = allocate_ref(session, RefKind.TRAINING_RUN)
        score = result.score if result else None
        session.add(
            TrainingRun(
                run_id=uuid7(),
                ref=ref,
                agent_ref=agent_ref,
                playbook_id=issued.playbook_id if issued else "none",
                playbook_version=issued.version if issued else "0",
                playbook_digest=issued.digest() if issued else "",
                # Recorded even when nothing was scored. "This specialty had
                # no fair question" is a statement about a *particular*
                # catalogue, and it stops being checkable the moment the
                # record cannot say which one.
                catalogue_digest=(
                    result.catalogue_digest if result else catalogue_digest()
                ),
                replications=result.replications if result else self._suite.replications,
                specialty=sorted(d.value for d in specialty),
                scenarios=score.scenarios if score else 0,
                caught=score.caught if score else 0,
                missed=score.missed if score else 0,
                false_alarms=score.false_alarms if score else 0,
                true_silences=score.true_silences if score else 0,
                effect_correct=score.effect_correct if score else 0,
                effect_wrong=score.effect_wrong if score else 0,
                effect_unscored=score.effect_unscored if score else 0,
                unscored_items=score.unscored_items if score else 0,
                catch_rate=_text(score.catch_rate) if score else None,
                false_alarm_rate=_text(score.false_alarm_rate) if score else None,
                effect_accuracy=_text(score.effect_accuracy) if score else None,
                verdict=verdict.value,
                reason=reason,
                standard=self._standard.as_payload(),
                measured_at=moment,
            )
        )
        session.flush()

        if result is not None:
            for row in result.marks:
                session.add(
                    ScenarioMark(
                        mark_id=uuid7(),
                        run_ref=ref,
                        scenario_id=row.scenario_id,
                        alleged=sorted(
                            {*(d.value for d in row.caught), *(d.value for d in row.false_alarms)}
                        ),
                        caught=sorted(d.value for d in row.caught),
                        missed=sorted(d.value for d in row.missed),
                        false_alarms=sorted(d.value for d in row.false_alarms),
                        true_silences=sorted(d.value for d in row.true_silences),
                        unscored=sorted(d.value for d in row.unscored),
                        effect_call=row.effect_call,
                        observed=str(row.observed),
                    )
                )
            session.flush()

        self._ledger.append(
            session,
            kind=(
                EventKind.ONBOARDING_REFUSED
                if verdict is TrainingVerdict.FAILED
                else EventKind.AGENT_SCORED
            ),
            actor=Actor.SYSTEM,
            subject=agent_ref,
            payload={
                "training_run": ref,
                "verdict": verdict.value,
                "reason": reason,
                "playbook": issued.describe() if issued else None,
                "specialty": sorted(d.value for d in specialty),
                "score": score.as_payload() if score else None,
                "caveat": (
                    "Institutional competence on planted effects, not market "
                    "truth. An agent calibrated here may still be miscalibrated "
                    "on a real market."
                ),
            },
            at=moment,
        )
        return TrainingOutcome(ref, agent_ref, verdict, reason, specialty, result)

    def latest(self, session: Session, agent_ref: str) -> TrainingRun | None:
        return session.execute(
            sa.select(TrainingRun)
            .where(TrainingRun.agent_ref == agent_ref)
            .order_by(TrainingRun.measured_at.desc(), TrainingRun.ref.desc())
            .limit(1)
        ).scalar_one_or_none()

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _coverage(session: Session, agent_ref: str) -> tuple[str, ...]:
        from aurelis.agents.tables import AgentCoverage

        exists = session.execute(
            sa.select(Agent.ref).where(Agent.ref == agent_ref)
        ).scalar_one_or_none()
        if exists is None:
            raise KeyError(f"no agent {agent_ref!r} to onboard")
        return tuple(
            session.execute(
                sa.select(AgentCoverage.charter_id)
                .where(AgentCoverage.agent_ref == agent_ref)
                .order_by(AgentCoverage.charter_id)
            ).scalars()
        )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def default_playbook() -> Playbook:
    """The shipped procedure, for callers that do not want to import two names."""
    return INCUMBENT


def blocked_states() -> frozenset[AgentState]:
    """States an agent that failed onboarding may hold."""
    return frozenset({AgentState.HIRED, AgentState.ONBOARDING, AgentState.RETRAINING})
