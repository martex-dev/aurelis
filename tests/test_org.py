"""The org chart: charters, desks, the launch roster, and resolved authority.

Most of this is checked at import by ``validate_registry`` and the roster's own
``_validate``. These tests assert the properties those checks defend, so a
future change that removes a check does not silently remove the guarantee.
"""

from __future__ import annotations

import pytest

from aurelis.core.enums import ModelTier
from aurelis.org import (
    CHARTERS,
    DEPARTMENTS,
    DESKS,
    LAUNCH_ROSTER,
    Department,
    ReadView,
    ToolScope,
    WriteScope,
    resolve_authority,
)
from aurelis.org.desks import DeskStatus
from aurelis.org.registry import validate_registry

# ----------------------------------------------------------------- structure


def test_the_full_roster_exists() -> None:
    """All seventy-six charters, from day one."""
    assert len(CHARTERS) == 76
    assert len(DEPARTMENTS) == 10
    assert len(DESKS) == 7


def test_charter_numbers_are_dense_from_one() -> None:
    """The numbers are cited in docs/02-organization.md and must agree."""
    assert sorted(c.number for c in CHARTERS.values()) == list(range(1, 77))


def test_every_department_has_charters() -> None:
    for department in Department:
        held = [c for c in CHARTERS.values() if c.department is department]
        assert held, f"{department} has no charters"


def test_registry_validates() -> None:
    validate_registry()


def test_only_crypto_is_open() -> None:
    """Declaring seven desks is a roadmap; opening one is a commitment."""
    active = [d for d, spec in DESKS.items() if spec.status is DeskStatus.ACTIVE]
    assert [d.value for d in active] == ["crypto"]


def test_unopened_desks_say_when_they_open() -> None:
    """An empty desk should read as scheduled, not forgotten."""
    for desk, spec in DESKS.items():
        assert spec.opens_at_milestone, f"{desk} does not say when it opens"


# ----------------------------------------------------- separation of duties


def test_only_risk_may_assess_risk() -> None:
    """The single most important boundary in the company."""
    holders = [c for c in CHARTERS.values() if WriteScope.RISK_ASSESSMENT in c.write_scopes]
    assert holders
    assert all(c.department is Department.PORTFOLIO_AND_RISK for c in holders)


def test_researchers_cannot_assess_risk() -> None:
    for charter_id in ("research.quant", "research.lead", "strategy.architect"):
        assert WriteScope.RISK_ASSESSMENT not in CHARTERS[charter_id].write_scopes


def test_researchers_cannot_reach_a_broker() -> None:
    for charter_id in ("research.quant", "strategy.architect", "intel.technical_analyst"):
        assert ToolScope.BROKER_SUBMIT not in CHARTERS[charter_id].tools


def test_exactly_one_charter_reaches_a_broker() -> None:
    holders = [cid for cid, c in CHARTERS.items() if ToolScope.BROKER_SUBMIT in c.tools]
    assert holders == ["trading.execution"]


def test_preregistration_has_one_custodian() -> None:
    holders = [cid for cid, c in CHARTERS.items() if WriteScope.REGISTRATION in c.write_scopes]
    assert holders == ["gov.registrar"]


def test_sealed_data_has_one_gatekeeper() -> None:
    holders = [cid for cid, c in CHARTERS.items() if WriteScope.SEALED_QUERY in c.write_scopes]
    assert holders == ["gov.custodian"]


def test_org_changes_have_one_proposer() -> None:
    holders = [cid for cid, c in CHARTERS.items() if WriteScope.ORG_CHANGE in c.write_scopes]
    assert holders == ["exec.org_development"]


def test_unrestricted_sight_is_confined_to_audit_and_governance() -> None:
    """Granting it elsewhere destroys the information asymmetry."""
    holders = [cid for cid, c in CHARTERS.items() if ReadView.EVERYTHING in c.read_views]
    assert holders
    for cid in holders:
        assert CHARTERS[cid].department in (
            Department.AUDIT_AND_GOVERNANCE,
            Department.INSTITUTIONAL_GOVERNANCE,
        )


def test_no_charter_may_write_a_measurement() -> None:
    """Agents interpret; engines compute. There is no scope for a number."""
    assert not any(s.value in ("run", "result", "metric") for s in WriteScope)


# ------------------------------------------------------------ launch roster


def test_launch_roster_covers_every_charter_exactly_once() -> None:
    held = [cid for agent in LAUNCH_ROSTER for cid in agent.coverage]
    assert sorted(held) == sorted(CHARTERS)
    assert len(held) == len(set(held))


def test_launch_roster_is_seventeen_agents() -> None:
    assert len(LAUNCH_ROSTER) == 17


def test_designer_and_critic_are_different_agents() -> None:
    """An agent that reviews its own design is not a review."""
    holder = {cid: a.handle for a in LAUNCH_ROSTER for cid in a.coverage}
    assert holder["strategy.architect"] != holder["strategy.critic"]


def test_risk_and_portfolio_are_different_agents() -> None:
    """The agent that wants the exposure must not approve it."""
    holder = {cid: a.handle for a in LAUNCH_ROSTER for cid in a.coverage}
    assert holder["risk.chief"] != holder["risk.portfolio_manager"]


# ------------------------------------------------------- resolved authority


def test_authority_is_the_union_of_charters() -> None:
    both = resolve_authority(("intel.technical_analyst", "intel.news_analyst"))
    technical = resolve_authority(("intel.technical_analyst",))
    news = resolve_authority(("intel.news_analyst",))
    assert both.tools == technical.tools | news.tools
    assert both.write_scopes == technical.write_scopes | news.write_scopes


def test_splitting_coverage_can_only_narrow_authority() -> None:
    """The property that makes role fission safe (ADR-0003).

    A generalist splitting into specialists must never leave either specialist
    able to do something the generalist could not.
    """
    for agent in LAUNCH_ROSTER:
        if len(agent.coverage) < 2:
            continue
        whole = resolve_authority(agent.coverage)
        for charter_id in agent.coverage:
            part = resolve_authority((charter_id,))
            assert part.read_views <= whole.read_views
            assert part.write_scopes <= whole.write_scopes
            assert part.tools <= whole.tools


def test_tier_is_the_highest_charter_held() -> None:
    """Cost follows the most demanding thing an agent is responsible for."""
    mixed = resolve_authority(("exec.company_manager", "intel.news_analyst"))
    assert mixed.tier is ModelTier.HIGH


def test_an_agent_must_hold_a_charter() -> None:
    with pytest.raises(ValueError, match="at least one charter"):
        resolve_authority(())


def test_unknown_charter_is_refused() -> None:
    with pytest.raises(KeyError, match="unknown charter"):
        resolve_authority(("intel.astrologer",))


def test_governance_is_mostly_free_to_run() -> None:
    """Eight of eleven officers are software wearing a badge."""
    governance = [
        c for c in CHARTERS.values() if c.department is Department.INSTITUTIONAL_GOVERNANCE
    ]
    free = [c for c in governance if c.tier is ModelTier.NONE]
    assert len(free) >= 7, "governance should cost almost nothing to run"
