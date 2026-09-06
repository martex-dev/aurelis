"""Detecting when the company should change shape.

The table below is `docs/02-organization.md` §6.2 as code. Each trigger names a
metric, a threshold and what it proposes, and a hit carries **the reading that
fired it** — so a proposal cannot be written without the measurement that
justifies it being attached to it.

Two rules keep this honest.

**A metric that could not be taken never fires a trigger.** `Reading.value` is
``None`` when the record cannot support the measurement, and a ``None`` is not
a small number. Firing on it would mean proposing to reorganise the company
because the instrumentation has a hole.

**Thresholds are declared here, not chosen per proposal.** A trigger whose
threshold is picked after the reading is a justification, not a trigger.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent, AgentState
from aurelis.orgdev.metrics import AgentMetrics, Reading, agent_metrics
from aurelis.orgdev.states import OrgChangeKind, TriggerKind

__all__ = ["TRIGGERS", "OrgTrigger", "TriggerHit", "scan"]


@dataclass(frozen=True, slots=True)
class OrgTrigger:
    """One declared reason to propose a change."""

    kind: TriggerKind
    metric: str
    comparison: str
    """``gte`` or ``lte``."""

    threshold: Decimal
    proposes: OrgChangeKind
    asks: str

    def fires(self, reading: Reading) -> bool:
        if reading.value is None:
            # Not a small number. A trigger that fired on an unmeasurable
            # reading would propose reorganising the company because the
            # instrumentation has a hole in it.
            return False
        if self.comparison == "gte":
            return reading.value >= self.threshold
        return reading.value <= self.threshold

    def describe(self) -> str:
        sign = ">=" if self.comparison == "gte" else "<="
        return f"{self.metric} {sign} {self.threshold} -> {self.proposes.value}"


TRIGGERS: tuple[OrgTrigger, ...] = (
    OrgTrigger(
        TriggerKind.BREADTH,
        "breadth",
        "gte",
        Decimal(5),
        OrgChangeKind.FISSION,
        asks=(
            "Is this agent standing in for so many charters that no "
            "measurement about any one of them is attributable to it?"
        ),
    ),
    OrgTrigger(
        TriggerKind.BACKLOG_DEPTH,
        "backlog_depth",
        "gte",
        Decimal(20),
        OrgChangeKind.FISSION,
        asks="Is work arriving faster than this agent can take it?",
    ),
    OrgTrigger(
        TriggerKind.RESPONSE_LATENCY,
        "backlog_age_hours",
        "gte",
        Decimal(168),
        OrgChangeKind.FISSION,
        asks="Has something been waiting a week for this agent?",
    ),
    OrgTrigger(
        TriggerKind.UNDERUSE,
        "throughput",
        "lte",
        Decimal(0),
        OrgChangeKind.FUSION,
        asks="Has this agent completed anything at all?",
    ),
    OrgTrigger(
        TriggerKind.SCENARIO_FAILURE,
        "scenario_catch_rate",
        "lte",
        Decimal("0.5"),
        OrgChangeKind.RETRAIN,
        asks=(
            "Does this agent miss more than half of the defects the training "
            "suite plants in its own specialty?"
        ),
    ),
    OrgTrigger(
        TriggerKind.CALIBRATION_DECAY,
        "calibration",
        "gte",
        Decimal("0.35"),
        OrgChangeKind.RETRAIN,
        asks="Are this agent's forecasts worse than a coin?",
    ),
)
"""The declared triggers. A closed table, versioned with the code.

``BREADTH`` is first and fires hardest, because it is the launch roster's
defining condition: seventeen agents stand in for seventy-six charters, and the
honest consequence is not that the other charters are idle but that **nothing
about them is attributable**. The company's own instrumentation is the first
thing its instrumentation says to fix.
"""


@dataclass(frozen=True, slots=True)
class TriggerHit:
    """A trigger that fired, and the reading that fired it."""

    trigger: OrgTrigger
    subject: str
    handle: str
    reading: Reading

    @property
    def evidence(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger.kind.value,
            "metric": self.trigger.metric,
            "value": str(self.reading.value),
            "comparison": self.trigger.comparison,
            "threshold": str(self.trigger.threshold),
            "detail": self.reading.detail,
            "asks": self.trigger.asks,
        }

    def describe(self) -> str:
        return (
            f"{self.handle} ({self.subject}): {self.trigger.metric} "
            f"{self.reading.value} vs {self.trigger.threshold} — "
            f"{self.trigger.proposes.value}"
        )


def scan(
    session: Session,
    *,
    triggers: Sequence[OrgTrigger] = TRIGGERS,
    subjects: Sequence[str] | None = None,
) -> tuple[TriggerHit, ...]:
    """Measure every working agent and report which declared triggers fired."""
    if subjects is None:
        refs = list(
            session.execute(
                sa.select(Agent.ref)
                .where(Agent.state.notin_((AgentState.RETIRED, AgentState.SUSPENDED)))
                .order_by(Agent.ref)
            ).scalars()
        )
    else:
        refs = list(subjects)

    hits: list[TriggerHit] = []
    for ref in refs:
        measured: AgentMetrics = agent_metrics(session, ref)
        for trigger in triggers:
            reading = measured.get(trigger.metric)
            if trigger.fires(reading):
                hits.append(TriggerHit(trigger, ref, measured.handle, reading))
    return tuple(hits)
