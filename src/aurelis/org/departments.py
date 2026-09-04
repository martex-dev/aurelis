"""The ten departments.

A closed registry in code, not rows an agent can invent. Departments are
structural: they decide who may write what, who attends which meeting, and
where a room appears in Mission Control. Something that structural should
change by repository edit and review, never at runtime.

Department ten, Institutional Governance, is a **service department**. Every
other department uses it; none reports to it. It locks preregistrations, holds
sealed data, scores forecasts and verifies the chain — and it has no authority
over research direction and replaces nobody.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["DEPARTMENTS", "Department", "DepartmentSpec"]


class Department(StrEnum):
    EXECUTIVE = "executive"
    MARKET_INTELLIGENCE = "market_intelligence"
    QUANTITATIVE_RESEARCH = "quantitative_research"
    STRATEGY_LABORATORY = "strategy_laboratory"
    PORTFOLIO_AND_RISK = "portfolio_and_risk"
    TRADING_OPERATIONS = "trading_operations"
    AUDIT_AND_GOVERNANCE = "audit_and_governance"
    KNOWLEDGE_AND_MEMORY = "knowledge_and_memory"
    INFRASTRUCTURE = "infrastructure"
    INSTITUTIONAL_GOVERNANCE = "institutional_governance"


@dataclass(frozen=True, slots=True)
class DepartmentSpec:
    department: Department
    name: str
    owns: str
    head_charter: str
    """The charter whose holder leads it. Checked against the charter registry
    at import, so a department can never point at a role that does not exist."""


DEPARTMENTS: dict[Department, DepartmentSpec] = {
    spec.department: spec
    for spec in (
        DepartmentSpec(
            Department.EXECUTIVE,
            "Executive / Mission Control",
            "Company direction, missions, priorities, org development, the Chair",
            "exec.company_manager",
        ),
        DepartmentSpec(
            Department.MARKET_INTELLIGENCE,
            "Market Intelligence",
            "Observation, evidence gathering, briefings, market state",
            "intel.head",
        ),
        DepartmentSpec(
            Department.QUANTITATIVE_RESEARCH,
            "Quantitative Research",
            "Hypotheses, experiments, statistics, modelling, research engineering",
            "research.lead",
        ),
        DepartmentSpec(
            Department.STRATEGY_LABORATORY,
            "Strategy Laboratory",
            "Strategy discovery, synthesis, debate, adversarial testing, validation",
            "strategy.head",
        ),
        DepartmentSpec(
            Department.PORTFOLIO_AND_RISK,
            "Portfolio & Risk",
            "Construction, allocation, exposure, correlation, risk authority",
            "risk.chief",
        ),
        DepartmentSpec(
            Department.TRADING_OPERATIONS,
            "Trading Operations",
            "Setup analysis, trade planning, approval, execution, monitoring",
            "trading.head",
        ),
        DepartmentSpec(
            Department.AUDIT_AND_GOVERNANCE,
            "Audit & Governance",
            "Independent challenge of research, data, backtests, execution, agents",
            "audit.chief",
        ),
        DepartmentSpec(
            Department.KNOWLEDGE_AND_MEMORY,
            "Knowledge & Memory",
            "Institutional memory, archive, registries, ledger, knowledge graph",
            "knowledge.chief",
        ),
        DepartmentSpec(
            Department.INFRASTRUCTURE,
            "Infrastructure",
            "Data systems, compute, scheduling, runtime, observability, integrations",
            "infra.head",
        ),
        DepartmentSpec(
            Department.INSTITUTIONAL_GOVERNANCE,
            "Institutional Governance",
            "Preregistration, custody, evidence typing, forecast scoring, budget "
            "ledger — in service to the other nine",
            "gov.director",
        ),
    )
}
