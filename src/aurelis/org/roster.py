"""The launch roster: seventeen agents holding seventy-six charters.

Every charter is owned from day one. Launch agents are **generalists standing
in for future specialists**, and each entry says exactly which specialists it
covers — so an agent's own record is the evidence for its eventual split.

The company is recognisably itself immediately: an Executive that sets
missions, Intelligence that observes, Research that experiments, a Strategy Lab
that builds and attacks, Risk that can veto, Trading that only paper-trades,
Audit that challenges everyone, Knowledge that remembers, Infrastructure that
keeps it running, and Governance that makes cheating impossible.

An agent's resolved permissions are the **union** of the scopes of every
charter it holds. That is what makes fission safe: splitting a coverage set can
only ever narrow authority, never widen it, and total coverage is conserved.
"""

from __future__ import annotations

from dataclasses import dataclass

from aurelis.org.charters import CHARTERS, Seniority
from aurelis.org.departments import Department
from aurelis.org.desks import Desk

__all__ = ["LAUNCH_ROSTER", "LaunchAgent"]


@dataclass(frozen=True, slots=True)
class LaunchAgent:
    """One agent in the founding roster."""

    handle: str
    """Short name colleagues use. The reference code (AG-0001) is allocated at
    hire time; this is the human-readable identity."""

    department: Department
    coverage: tuple[str, ...]
    seniority: Seniority
    desk: Desk | None = None
    note: str = ""


LAUNCH_ROSTER: tuple[LaunchAgent, ...] = (
    LaunchAgent(
        "CEO",
        Department.EXECUTIVE,
        ("exec.company_manager",),
        Seniority.DIRECTOR,
        note="Sets missions and arbitrates escalations. Never a researcher.",
    ),
    LaunchAgent(
        "CIO",
        Department.EXECUTIVE,
        ("exec.research_director", "exec.org_development"),
        Seniority.DIRECTOR,
        note="Research agenda plus org development until the two have enough "
        "work to justify separate heads.",
    ),
    LaunchAgent(
        "OPS",
        Department.EXECUTIVE,
        ("exec.operations_director", "exec.mission_orchestrator", "exec.chief_of_staff"),
        Seniority.LEAD,
        note="Also the Chair. Splits first when meeting volume grows.",
    ),
    LaunchAgent(
        "INTEL",
        Department.MARKET_INTELLIGENCE,
        (
            "intel.head",
            "intel.fundamental_analyst",
            "intel.news_analyst",
            "intel.sentiment_analyst",
            "intel.technical_analyst",
            "intel.macro_analyst",
            "intel.regime_analyst",
            "intel.alternative_data_analyst",
            "intel.source_reliability",
        ),
        Seniority.SENIOR,
        desk=Desk.CRYPTO,
        note="All nine Intelligence charters. The widest coverage in the "
        "company and therefore the first expected fission.",
    ),
    LaunchAgent(
        "LEAD-R",
        Department.QUANTITATIVE_RESEARCH,
        ("research.lead",),
        Seniority.LEAD,
        desk=Desk.CRYPTO,
    ),
    LaunchAgent(
        "QUANT",
        Department.QUANTITATIVE_RESEARCH,
        (
            "research.quant",
            "research.statistical",
            "research.backtest",
            "research.simulation",
            "research.ml",
            "research.factor",
            "research.data_scientist",
        ),
        Seniority.SENIOR,
        desk=Desk.CRYPTO,
    ),
    LaunchAgent(
        "ENG-R",
        Department.QUANTITATIVE_RESEARCH,
        ("research.engineer",),
        Seniority.SENIOR,
    ),
    LaunchAgent(
        "STRAT",
        Department.STRATEGY_LABORATORY,
        (
            "strategy.head",
            "strategy.architect",
            "strategy.discovery",
            "strategy.synthesizer",
        ),
        Seniority.LEAD,
        desk=Desk.CRYPTO,
    ),
    LaunchAgent(
        "CRITIC",
        Department.STRATEGY_LABORATORY,
        ("strategy.critic", "strategy.adversarial"),
        Seniority.SENIOR,
        desk=Desk.CRYPTO,
        note="Deliberately a different agent from STRAT. A designer who "
        "reviews their own design is not a review.",
    ),
    LaunchAgent(
        "VALID",
        Department.STRATEGY_LABORATORY,
        ("strategy.replication", "strategy.robustness", "strategy.validation"),
        Seniority.SENIOR,
        desk=Desk.CRYPTO,
    ),
    LaunchAgent(
        "RISK",
        Department.PORTFOLIO_AND_RISK,
        (
            "risk.chief",
            "risk.manager",
            "risk.exposure_analyst",
            "risk.correlation_analyst",
            "risk.stress_testing",
        ),
        Seniority.DIRECTOR,
        note="Holds the veto. Deliberately separate from PM: the agent that "
        "wants the exposure must not be the agent that approves it.",
    ),
    LaunchAgent(
        "PM",
        Department.PORTFOLIO_AND_RISK,
        ("risk.portfolio_manager", "risk.capital_allocation"),
        Seniority.LEAD,
    ),
    LaunchAgent(
        "TRADE",
        Department.TRADING_OPERATIONS,
        (
            "trading.head",
            "trading.market_setup",
            "trading.planner",
            "trading.approval",
            "trading.execution",
            "trading.position_monitor",
            "trading.post_trade",
        ),
        Seniority.SENIOR,
        desk=Desk.CRYPTO,
        note="Paper only. No live broker adapter exists in the repository.",
    ),
    LaunchAgent(
        "AUDIT",
        Department.AUDIT_AND_GOVERNANCE,
        (
            "audit.chief",
            "audit.research",
            "audit.data",
            "audit.backtest",
            "audit.execution",
            "audit.agent_behavior",
        ),
        Seniority.DIRECTOR,
        note="Sees everything. That is what makes it an auditor.",
    ),
    LaunchAgent(
        "KNOW",
        Department.KNOWLEDGE_AND_MEMORY,
        (
            "knowledge.chief",
            "knowledge.memory_keeper",
            "knowledge.archivist",
            "knowledge.strategy_registrar",
            "knowledge.hypothesis_ledger",
            "knowledge.graph_curator",
        ),
        Seniority.SENIOR,
    ),
    LaunchAgent(
        "INFRA",
        Department.INFRASTRUCTURE,
        (
            "infra.head",
            "infra.data_systems",
            "infra.compute",
            "infra.agent_runtime",
            "infra.observability",
            "infra.integrations",
        ),
        Seniority.SENIOR,
    ),
    LaunchAgent(
        "GOV",
        Department.INSTITUTIONAL_GOVERNANCE,
        (
            "gov.director",
            "gov.registrar",
            "gov.custodian",
            "gov.evidence_officer",
            "gov.forecast_scorer",
            "gov.ledger_officer",
            "gov.budget_officer",
            "gov.provenance_officer",
            "gov.skeptic",
            "gov.replication_officer",
            "gov.peer_reviewer",
        ),
        Seniority.SENIOR,
        note="Eight of these eleven are deterministic and cost nothing to run.",
    ),
)


def _validate() -> None:
    """Every charter owned exactly once, by an agent in its own department.

    Runs at import. A roster that silently dropped a charter would leave a
    region of the company's remit with nobody responsible for it, and the
    failure would not show up until something needed doing and nobody did it.
    """
    seen: dict[str, str] = {}
    for agent in LAUNCH_ROSTER:
        for charter_id in agent.coverage:
            charter = CHARTERS.get(charter_id)
            if charter is None:
                raise ValueError(f"{agent.handle} holds unknown charter {charter_id!r}")
            if charter_id in seen:
                raise ValueError(
                    f"charter {charter_id!r} is held by both {seen[charter_id]} "
                    f"and {agent.handle}; coverage must be unambiguous"
                )
            if charter.department is not agent.department:
                raise ValueError(
                    f"{agent.handle} is in {agent.department} but holds "
                    f"{charter_id!r}, which belongs to {charter.department}"
                )
            seen[charter_id] = agent.handle

    orphaned = sorted(set(CHARTERS) - set(seen))
    if orphaned:
        raise ValueError(
            f"{len(orphaned)} charter(s) have no owner in the launch roster: "
            f"{', '.join(orphaned)}. Every remit must belong to someone."
        )


_validate()
