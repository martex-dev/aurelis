"""The three permission axes.

Every agent's authority resolves to three closed vocabularies:

**Read scope** — which *views* it may build. A view is the entire world an
agent sees for a piece of work, so widening one is a registry change with a
test, and "what did the Strategy Critic know when it signed off?" is answered
by reading a table rather than tracing call sites.

**Write scope** — which entity kinds it may create. This is the axis with real
teeth: it is seeded into the database and enforced by trigger, so a researcher
cannot write a risk assessment even through raw SQL.

**Tool scope** — which capabilities it may invoke.

All three are enums rather than free strings, because a permission that can be
invented at runtime cannot be reviewed. Adding one is a repository edit.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ReadView", "ToolScope", "WriteScope"]


class WriteScope(StrEnum):
    """Entity kinds an agent may create.

    Three absences matter more than anything present:

    * There is no ``RUN`` or ``RESULT``. **No agent may write a number.**
      Metrics come from engines and carry the artifact hash they were read
      from.
    * There is no ``EVENT``. The ledger is append-only and written by the
      platform.
    * ``RISK_ASSESSMENT`` is held by risk charters and nothing else, so risk
      cannot be bypassed by an agent that would rather not be told no.
    """

    MARKET_OBSERVATION = "market_observation"
    BRIEFING = "briefing"
    MESSAGE = "message"
    TASK = "task"

    HYPOTHESIS = "hypothesis"
    EXPERIMENT_SPEC = "experiment_spec"
    FINDING = "finding"
    EVIDENCE = "evidence"
    OBJECTION = "objection"
    REPLICATION = "replication"

    REGISTRATION = "registration"
    """Locked and hashed. Held by the Registrar alone."""

    SEALED_QUERY = "sealed_query"
    """A counted query against held-out data. The Custodian alone."""

    STRATEGY_VERSION = "strategy_version"
    PROMOTION_GATE = "promotion_gate"

    RISK_ASSESSMENT = "risk_assessment"
    RISK_LIMIT = "risk_limit"
    PORTFOLIO_ALLOCATION = "portfolio_allocation"

    TRADE_PROPOSAL = "trade_proposal"
    TRADE_APPROVAL = "trade_approval"
    ORDER = "order"

    MEETING_TURN = "meeting_turn"
    DECISION = "decision"
    FORECAST = "forecast"

    AUDIT_RECORD = "audit_record"
    ALERT = "alert"
    LESSON = "lesson"
    KNOWLEDGE_EDGE = "knowledge_edge"
    ORG_CHANGE = "org_change"


class ReadView(StrEnum):
    """Registered views — the only way to widen what a charter can see.

    A view is deliberately narrow. The Designer of an experiment is never
    handed the generator parameters, because an agent told which features
    moved would not need to run the experiment.
    """

    COMPANY_STATE = "company.state"
    MISSION_BRIEF = "mission.brief"
    TASK_ASSIGNMENT = "task.assignment"

    DESK_MARKET_SNAPSHOT = "market.desk_snapshot"
    DESK_OBSERVATIONS = "market.desk_observations"
    SOURCE_RELIABILITY = "market.source_reliability"

    HYPOTHESIS_STATEMENT = "research.hypothesis"
    EXPERIMENT_DESIGN = "research.experiment_design"
    EXPERIMENT_RESULT = "research.experiment_result"
    PRIOR_ART = "research.prior_art"
    OPEN_OBJECTIONS = "research.open_objections"

    STRATEGY_SPEC = "strategy.spec"
    STRATEGY_EVIDENCE = "strategy.evidence"
    PROMOTION_GATES = "strategy.promotion_gates"

    PORTFOLIO_BOOK = "portfolio.book"
    RISK_LIMITS = "risk.limits"
    EXPOSURE_SNAPSHOT = "risk.exposure"

    APPROVED_INSTRUCTIONS = "trading.approved_instructions"
    POSITION_STATE = "trading.positions"

    MEETING_EVIDENCE_PACK = "meeting.evidence_pack"
    MEETING_TRANSCRIPT = "meeting.transcript"

    INSTITUTIONAL_MEMORY = "knowledge.memory"
    GRAVEYARD = "knowledge.graveyard"

    AGENT_METRICS = "org.agent_metrics"
    ORG_METRICS = "org.metrics"

    EVERYTHING = "audit.everything"
    """What makes an auditor an auditor. Held only by Audit & Governance."""

    SYSTEM_HEALTH = "infra.system_health"
    LEDGER = "governance.ledger"


class ToolScope(StrEnum):
    """Capabilities an agent may invoke.

    Note what is *not* here for most charters: ``BROKER_SUBMIT`` exists but is
    held by exactly one charter, and no live adapter is registered behind it.
    """

    DATA_OHLCV = "data.ohlcv"
    DATA_FUNDAMENTALS = "data.fundamentals"
    DATA_NEWS = "data.news"
    DATA_SENTIMENT = "data.sentiment"
    DATA_ONCHAIN = "data.onchain"

    ENGINE_BACKTEST = "engine.backtest"
    ENGINE_FEATURES = "engine.features"
    ENGINE_STATISTICS = "engine.statistics"
    ENGINE_SIMULATION = "engine.simulation"

    STATS_SIGNIFICANCE = "stats.significance"
    STATS_CALIBRATION = "stats.calibration"
    INTEGRITY_LEAK_SCAN = "integrity.leak_scan"
    INTEGRITY_POINT_IN_TIME = "integrity.point_in_time"

    PORTFOLIO_CORRELATION = "portfolio.correlation"
    PORTFOLIO_ATTRIBUTION = "portfolio.attribution"

    BROKER_SUBMIT = "broker.submit"
    """Paper and simulation only. No live adapter exists — see ADR-0006."""

    COMMS_POST = "comms.post"
    COMMS_MESSAGE = "comms.message"
    COMMS_ESCALATE = "comms.escalate"
    COMMS_CALL_MEETING = "comms.call_meeting"

    MEMORY_SEARCH = "memory.search"
    LEDGER_QUERY = "ledger.query"
