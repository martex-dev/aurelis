"""The organization: departments, desks, charters, and the launch roster.

A closed registry in code. Departments, desks and the seventy-six charters
change by repository edit and review; agents that *hold* those charters are
rows. That separation is the growth mechanism (ADR-0003): the company goes
from seventeen agents to a hundred without the runtime changing, because
growth is data.
"""

from aurelis.org.charters import CHARTERS, Charter, Seniority, charters_for_department
from aurelis.org.departments import DEPARTMENTS, Department, DepartmentSpec
from aurelis.org.desks import DESKS, Desk, DeskSpec, DeskStatus, active_desks
from aurelis.org.registry import (
    ResolvedAuthority,
    charter,
    resolve_authority,
    validate_registry,
)
from aurelis.org.roster import LAUNCH_ROSTER, LaunchAgent
from aurelis.org.scopes import ReadView, ToolScope, WriteScope

__all__ = [
    "CHARTERS",
    "DEPARTMENTS",
    "DESKS",
    "LAUNCH_ROSTER",
    "Charter",
    "Department",
    "DepartmentSpec",
    "Desk",
    "DeskSpec",
    "DeskStatus",
    "LaunchAgent",
    "ReadView",
    "ResolvedAuthority",
    "Seniority",
    "ToolScope",
    "WriteScope",
    "active_desks",
    "charter",
    "charters_for_department",
    "resolve_authority",
    "validate_registry",
]
