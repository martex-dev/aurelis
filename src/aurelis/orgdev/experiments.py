"""Experiments on the company's own shape.

``CLAUDE.md`` §16 asks questions nobody can answer by thinking about them:

    Does adding an adversarial researcher reduce false discoveries?
    Do three technical analysts outperform two?
    Which agents duplicate each other?

M10 built the instrument. A **panel** is a set of roles, each contributing the
critique procedure its charter issues, run over the same twelve worlds with the
same measured answers. Two panels, one difference between them, and the counts
settle it.

How a panel reaches a verdict:

**Allegations are the union.** A room raises an objection if anyone in it does.
That is how a review actually works — a defect one specialist sees does not go
unraised because the others missed it — and it is why a panel of narrow
specialists can beat a generalist without any member being better than it.

**The effect call is the majority**, with a tie resolved towards *no effect*.
A room that splits on whether there is an edge has not found one.

The union rule has a consequence the company should want to know about, and it
is the most useful thing this module produces: **adding a member whose
procedure is already covered changes nothing at all.** Not a little — nothing,
exactly, because the union of a set with a subset of itself is the set.

Which makes the standing questions answer more sharply than they were asked.
Adding an adversarial researcher to a research panel takes catches from 4 to 7
with no more false alarms — but not because it is adversarial. It is because
its specialty covers three defects nobody else in the room was asked about.
Adding a *second* critic with the same specialty moves nothing. Three narrow
specialists whose specialties happen to union to a generalist's score exactly
what the generalist scores.

So the measured answer to "do more agents help?" is: **only when they widen
what the room is asked.** Headcount is not capability, and coverage is. That is
`CLAUDE.md` §16 as arithmetic rather than as a warning in a document.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.engines.synthetic.scenarios import catalogue_digest
from aurelis.meetings.types import ObjectionType
from aurelis.orgdev.tables import OrgExperiment
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger
from aurelis.training.critique import Critique, apply_playbook
from aurelis.training.playbook import playbook_for, specialty_of
from aurelis.training.scoring import Mark, Scorecard, mark, tally
from aurelis.training.suite import TrainingSuite

__all__ = ["Panel", "PanelResult", "OrgExperiments", "STANDING_QUESTIONS"]


@dataclass(frozen=True, slots=True)
class Panel:
    """A set of roles, sitting together over the same evidence."""

    name: str
    members: tuple[str, ...]
    """Charter ids. One agent per charter, which is the Stage-5 shape."""

    @property
    def specialty(self) -> frozenset[ObjectionType]:
        return specialty_of(self.members)

    def describe(self) -> str:
        return f"{self.name} ({len(self.members)}): {', '.join(self.members)}"


@dataclass(frozen=True, slots=True)
class PanelResult:
    """What one panel found across the whole catalogue."""

    panel: Panel
    marks: tuple[Mark, ...]
    score: Scorecard

    def describe(self) -> str:
        return f"{self.panel.name}: {self.score.describe()}"


def run_panel(panel: Panel, suite: TrainingSuite) -> PanelResult:
    """Sit the panel down in front of every scenario and mark what it says."""
    marks: list[Mark] = []
    for scen in suite.scenarios:
        truth = suite.bench.truth(scen, replications=suite.replications)
        seats: list[Critique] = []
        for charter_id in panel.members:
            issued = playbook_for((charter_id,))
            if issued is None:
                continue
            seats.append(apply_playbook(issued, scen, bench=suite.bench))
        if not seats:
            continue
        room = _combine(seats, scen.scenario_id, panel.name)
        marks.append(mark(room, truth))
    return PanelResult(panel=panel, marks=tuple(marks), score=tally(marks))


def _combine(seats: Sequence[Critique], scenario_id: str, name: str) -> Critique:
    """The room's position from its members'.

    Union on allegations, majority on the effect call with ties resolved
    towards no effect. ``considered`` is the union too: a defect nobody in the
    room was asked about is not a silence to the room's credit, so it must not
    be counted as one.
    """
    alleged: set[ObjectionType] = set()
    considered: set[ObjectionType] = set()
    for seat in seats:
        alleged |= seat.alleged
        considered |= seat.considered
    votes = sum(1 for seat in seats if seat.calls_effect_real)
    return Critique(
        scenario_id=scenario_id,
        playbook=f"panel:{name}",
        alleged=frozenset(alleged),
        calls_effect_real=votes * 2 > len(seats),
        observed=seats[0].observed,
        considered=frozenset(considered),
        detail={"seats": ", ".join(seat.playbook for seat in seats)},
    )


STANDING_QUESTIONS: tuple[tuple[str, Panel, Panel], ...] = (
    (
        "Does adding an adversarial researcher reduce false discoveries?",
        Panel("research only", ("research.backtest", "research.statistical")),
        Panel(
            "research + adversarial",
            ("research.backtest", "research.statistical", "strategy.adversarial"),
        ),
    ),
    (
        "Do three specialists beat one generalist?",
        Panel("one generalist critic", ("strategy.critic",)),
        Panel(
            "three narrow specialists",
            ("audit.data", "audit.research", "risk.stress_testing"),
        ),
    ),
    (
        "Does a second critic with the same procedure add anything?",
        Panel("one critic", ("strategy.critic",)),
        Panel("two critics", ("strategy.critic", "strategy.adversarial")),
    ),
)
"""The questions the company asks about itself first.

The third is the one worth reading. ``strategy.critic`` and
``strategy.adversarial`` are issued the *same* procedure over the *same*
taxonomy, so the second seat is a duplicate — and the experiment reports, in
counts, that it changes nothing. Headcount is not capability.
"""


class OrgExperiments:
    """Runs panel comparisons and records them."""

    __slots__ = ("_suite", "_ledger", "_clock")

    def __init__(
        self,
        suite: TrainingSuite | None = None,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._suite = suite or TrainingSuite()
        self._ledger = ledger or Ledger(self._clock)

    @property
    def suite(self) -> TrainingSuite:
        return self._suite

    def compare(self, control: Panel, treatment: Panel) -> tuple[PanelResult, PanelResult]:
        return run_panel(control, self._suite), run_panel(treatment, self._suite)

    def run(
        self,
        session: Session,
        *,
        question: str,
        control: Panel,
        treatment: Panel,
        at: dt.datetime | None = None,
    ) -> OrgExperiment:
        """Run both panels, decide which won, and record it either way."""
        moment = at or self._clock.now()
        before, after = self.compare(control, treatment)
        verdict, detail = _verdict(before.score, after.score)

        ref = allocate_ref(session, RefKind.ORG_EXPERIMENT)
        row = OrgExperiment(
            experiment_id=uuid7(),
            ref=ref,
            question=question,
            control_name=control.name,
            treatment_name=treatment.name,
            control_panel=list(control.members),
            treatment_panel=list(treatment.members),
            catalogue_digest=catalogue_digest(),
            replications=self._suite.replications,
            control_caught=before.score.caught,
            control_missed=before.score.missed,
            control_false_alarms=before.score.false_alarms,
            treatment_caught=after.score.caught,
            treatment_missed=after.score.missed,
            treatment_false_alarms=after.score.false_alarms,
            verdict=verdict,
            detail=detail,
            ran_at=moment,
        )
        session.add(row)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.ORG_EXPERIMENT_RUN,
            actor=Actor.SYSTEM,
            subject=ref,
            payload={
                "question": question,
                "control": control.describe(),
                "treatment": treatment.describe(),
                "control_score": before.score.as_payload(),
                "treatment_score": after.score.as_payload(),
                "verdict": verdict,
                "detail": detail,
                "caveat": (
                    "measured on planted defects, not on a market; and the "
                    "panels differ in procedure, not in reasoning ability"
                ),
            },
            at=moment,
        )
        return row


def _verdict(control: Scorecard, treatment: Scorecard) -> tuple[str, str]:
    """Which panel did better, on counts.

    Rates would hide the denominator: a panel that simply looked at fewer
    questions could keep a perfect catch rate while finding less. Counts cannot
    be gamed that way, and it is the same reason the playbook regression gate
    compares them.
    """
    caught = treatment.caught - control.caught
    alarms = treatment.false_alarms - control.false_alarms
    detail = (
        f"caught {control.caught} -> {treatment.caught}, "
        f"false alarms {control.false_alarms} -> {treatment.false_alarms}"
    )
    if caught == 0 and alarms == 0:
        return (
            "no_difference",
            detail + " — identical. Headcount is not capability.",
        )
    if caught >= 0 and alarms <= 0:
        return "treatment_better", detail
    if caught <= 0 and alarms >= 0:
        return "control_better", detail
    return (
        "mixed",
        detail + " — it found more and cried wolf more; which is better is a "
        "policy question, not a measurement",
    )
