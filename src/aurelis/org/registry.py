"""Resolving the org chart into authority.

Two jobs.

**Resolution.** An agent holds a coverage set of charters; its authority is the
union of their scopes. Union rather than intersection is what makes fission
safe: splitting a coverage set can only narrow what the resulting agents may
do, never widen it. A test asserts that property directly.

**Validation.** The registry is checked at import — every department's head
charter exists, charter numbers are dense from 1, ids match their department
prefix, and the separations of duty that the whole design rests on actually
hold. A permission model nobody checks is a diagram.
"""

from __future__ import annotations

from dataclasses import dataclass

from aurelis.core.enums import ModelTier
from aurelis.org.charters import CHARTERS, Charter, Seniority
from aurelis.org.departments import DEPARTMENTS, Department
from aurelis.org.scopes import ReadView, ToolScope, WriteScope

__all__ = ["ResolvedAuthority", "charter", "resolve_authority", "validate_registry"]

_TIER_ORDER = (ModelTier.NONE, ModelTier.LOW, ModelTier.MID, ModelTier.HIGH)

#: Prefix each department's charter ids must use, so an id is self-describing.
_PREFIXES: dict[Department, str] = {
    Department.EXECUTIVE: "exec",
    Department.MARKET_INTELLIGENCE: "intel",
    Department.QUANTITATIVE_RESEARCH: "research",
    Department.STRATEGY_LABORATORY: "strategy",
    Department.PORTFOLIO_AND_RISK: "risk",
    Department.TRADING_OPERATIONS: "trading",
    Department.AUDIT_AND_GOVERNANCE: "audit",
    Department.KNOWLEDGE_AND_MEMORY: "knowledge",
    Department.INFRASTRUCTURE: "infra",
    Department.INSTITUTIONAL_GOVERNANCE: "gov",
}


@dataclass(frozen=True, slots=True)
class ResolvedAuthority:
    """What an agent holding a coverage set may see, write and invoke."""

    coverage: tuple[str, ...]
    read_views: frozenset[ReadView]
    write_scopes: frozenset[WriteScope]
    tools: frozenset[ToolScope]
    tier: ModelTier
    seniority: Seniority
    departments: frozenset[Department]

    def may_read(self, view: ReadView) -> bool:
        return view in self.read_views or ReadView.EVERYTHING in self.read_views

    def may_write(self, scope: WriteScope) -> bool:
        return scope in self.write_scopes

    def may_use(self, tool: ToolScope) -> bool:
        return tool in self.tools


def charter(charter_id: str) -> Charter:
    try:
        return CHARTERS[charter_id]
    except KeyError:
        raise KeyError(
            f"unknown charter {charter_id!r}. Charters are a closed registry; "
            "add it to aurelis.org.charters rather than at runtime."
        ) from None


def resolve_authority(
    coverage: tuple[str, ...] | list[str], seniority: Seniority | None = None
) -> ResolvedAuthority:
    """Union the scopes of every charter in ``coverage``."""
    if not coverage:
        raise ValueError("an agent must hold at least one charter")

    held = [charter(cid) for cid in coverage]
    tier = max((c.tier for c in held), key=_TIER_ORDER.index)
    rank = seniority or max(
        (c.seniority for c in held),
        key=(Seniority.JUNIOR, Seniority.SENIOR, Seniority.LEAD, Seniority.DIRECTOR).index,
    )
    return ResolvedAuthority(
        coverage=tuple(coverage),
        read_views=frozenset(v for c in held for v in c.read_views),
        write_scopes=frozenset(s for c in held for s in c.write_scopes),
        tools=frozenset(t for c in held for t in c.tools),
        tier=tier,
        seniority=rank,
        departments=frozenset(c.department for c in held),
    )


# --------------------------------------------------------------- validation


def validate_registry() -> None:
    """Check the whole org chart. Called at import and by ``aurelis doctor``."""
    _check_numbering()
    _check_department_heads()
    _check_id_prefixes()
    _check_separations_of_duty()


def _check_numbering() -> None:
    numbers = sorted(c.number for c in CHARTERS.values())
    expected = list(range(1, len(CHARTERS) + 1))
    if numbers != expected:
        missing = sorted(set(expected) - set(numbers))
        duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
        raise ValueError(
            f"charter numbering is not dense from 1: missing={missing}, "
            f"duplicated={duplicated}. The numbers are cited in "
            "docs/02-organization.md and must agree with it."
        )


def _check_department_heads() -> None:
    for spec in DEPARTMENTS.values():
        head = CHARTERS.get(spec.head_charter)
        if head is None:
            raise ValueError(
                f"department {spec.department} names head charter "
                f"{spec.head_charter!r}, which does not exist"
            )
        if head.department is not spec.department:
            raise ValueError(
                f"department {spec.department} names head {spec.head_charter!r}, "
                f"but that charter belongs to {head.department}"
            )


def _check_id_prefixes() -> None:
    for cid, spec in CHARTERS.items():
        expected = _PREFIXES[spec.department]
        if not cid.startswith(f"{expected}."):
            raise ValueError(
                f"charter {cid!r} is in {spec.department} and must start with "
                f"{expected!r} so its id says where it belongs"
            )


def _check_separations_of_duty() -> None:
    """The separations the architecture actually rests on.

    Each of these is a claim made in ``docs/04-domain-model.md`` §9. Asserting
    them here means a careless charter edit fails at import rather than
    quietly widening someone's authority.
    """
    _only(
        WriteScope.RISK_ASSESSMENT,
        Department.PORTFOLIO_AND_RISK,
        "only Risk may assess risk, or risk is bypassable",
    )
    _only(
        WriteScope.RISK_LIMIT,
        Department.PORTFOLIO_AND_RISK,
        "limits are Risk's to set",
    )
    _only(
        WriteScope.ORDER,
        Department.TRADING_OPERATIONS,
        "only Trading Operations reaches a broker",
    )
    _only(
        WriteScope.TRADE_APPROVAL,
        Department.TRADING_OPERATIONS,
        "approval is an operational gate, not a research act",
    )
    _only(
        WriteScope.AUDIT_RECORD,
        Department.AUDIT_AND_GOVERNANCE,
        Department.INSTITUTIONAL_GOVERNANCE,
        reason="audit findings come from independent departments",
    )

    _exactly(WriteScope.REGISTRATION, "gov.registrar", "preregistration has one custodian")
    _exactly(WriteScope.SEALED_QUERY, "gov.custodian", "sealed data has one gatekeeper")
    _exactly(ToolScope.BROKER_SUBMIT, "trading.execution", "one charter reaches a broker")
    _exactly(WriteScope.ORG_CHANGE, "exec.org_development", "org changes have one proposer")

    holders = {cid for cid, c in CHARTERS.items() if ReadView.EVERYTHING in c.read_views}
    outside = {
        cid
        for cid in holders
        if CHARTERS[cid].department
        not in (Department.AUDIT_AND_GOVERNANCE, Department.INSTITUTIONAL_GOVERNANCE)
    }
    if outside:
        raise ValueError(
            f"{sorted(outside)} hold the EVERYTHING view outside Audit and "
            "Governance. Unrestricted sight is what makes an auditor an auditor; "
            "granting it elsewhere destroys the information asymmetry the "
            "research design depends on."
        )

    writers_of_numbers = {
        cid
        for cid, c in CHARTERS.items()
        if any(s.value in ("run", "result", "metric") for s in c.write_scopes)
    }
    if writers_of_numbers:  # pragma: no cover - guarded by the WriteScope enum
        raise ValueError(
            f"{sorted(writers_of_numbers)} claim authority to write measurements. "
            "No agent writes a number; engines do."
        )


def _only(scope: object, *departments: object, reason: str = "") -> None:
    allowed = {d for d in departments if isinstance(d, Department)}
    note = reason or (departments[-1] if isinstance(departments[-1], str) else "")
    offenders = sorted(
        cid
        for cid, c in CHARTERS.items()
        if scope in (*c.write_scopes, *c.tools) and c.department not in allowed
    )
    if offenders:
        raise ValueError(f"{offenders} hold {scope} outside {sorted(allowed)}: {note}")


def _exactly(scope: object, charter_id: str, reason: str) -> None:
    holders = sorted(
        cid for cid, c in CHARTERS.items() if scope in (*c.write_scopes, *c.tools)
    )
    if holders != [charter_id]:
        raise ValueError(
            f"{scope} should be held by exactly {charter_id!r} ({reason}), "
            f"but is held by {holders}"
        )


validate_registry()
