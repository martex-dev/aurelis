"""Org development: the company changes its own shape, and measures whether it helped.

Three things live here, and they are the same discipline applied to the company
that the rest of the system applies to research.

**Metrics** are measured from the record, and a metric that cannot be computed
is absent rather than zero -- because a zero here is a reason to hire somebody.

**Changes are preregistered.** An ``OrgChange`` hashes its predicted effect and
its measurement plan before the Board sees it, and a trigger freezes those
columns afterwards (ADR-0012). The effect is measured after a declared window
and recorded whichever way it comes out.

**Coverage is conserved.** A fission moves charters by a single UPDATE; nothing
is ever deleted and recreated, so no charter is held by nobody at any instant
and none is held by two people. The database refuses every deletion that would
orphan one, including the cascade from retiring an agent.

And **org experiments** turn CLAUDE.md 16 into arithmetic: two panels, the same
twelve worlds from M10, and a count.
"""

from __future__ import annotations

from aurelis.orgdev.detection import TRIGGERS, OrgTrigger, TriggerHit, scan
from aurelis.orgdev.development import (
    AppliedChange,
    MeasuredEffect,
    OrgDevelopment,
    Prediction,
)
from aurelis.orgdev.experiments import (
    STANDING_QUESTIONS,
    OrgExperiments,
    Panel,
    PanelResult,
    run_panel,
)
from aurelis.orgdev.handover import Handover, HandoverReport
from aurelis.orgdev.metrics import (
    COMPANY,
    METRICS,
    AgentMetrics,
    Reading,
    agent_metrics,
    charter_starvation,
    company_metrics,
    overlap,
    read_metric,
)
from aurelis.orgdev.states import (
    EffectVerdict,
    OrgChangeKind,
    OrgChangeState,
    TriggerKind,
)
from aurelis.orgdev.tables import (
    CoverageTransfer,
    OrgChange,
    OrgExperiment,
    OrgMetricSnapshot,
)

__all__ = [
    "COMPANY",
    "METRICS",
    "STANDING_QUESTIONS",
    "TRIGGERS",
    "AgentMetrics",
    "AppliedChange",
    "CoverageTransfer",
    "EffectVerdict",
    "Handover",
    "HandoverReport",
    "MeasuredEffect",
    "OrgChange",
    "OrgChangeKind",
    "OrgChangeState",
    "OrgDevelopment",
    "OrgExperiment",
    "OrgExperiments",
    "OrgMetricSnapshot",
    "OrgTrigger",
    "Panel",
    "PanelResult",
    "Prediction",
    "Reading",
    "TriggerHit",
    "TriggerKind",
    "agent_metrics",
    "charter_starvation",
    "company_metrics",
    "overlap",
    "read_metric",
    "run_panel",
    "scan",
]
