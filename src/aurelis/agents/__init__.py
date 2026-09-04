"""The agent runtime: who works here, what they may do, and how a turn runs.

An agent is a row that holds a coverage set of charters. Its authority is the
union of those charters' scopes, resolved at load and enforced in two places:
views are built rather than filtered, and write scope is a database trigger.
"""

from aurelis.agents.guards import SCOPE_GUARDS, install_guards, verify_guards
from aurelis.agents.loop import AgentContext, AgentWorker, TurnResult, register_handler
from aurelis.agents.roster import Roster, StaffedAgent
from aurelis.agents.tables import Agent, AgentCoverage, AgentState, ToolCall
from aurelis.agents.tools import ToolBox, ToolResult, register_tool, registered_tools
from aurelis.agents.views import ViewContext, build_view, register_view, registered_views

__all__ = [
    "SCOPE_GUARDS",
    "Agent",
    "AgentContext",
    "AgentCoverage",
    "AgentState",
    "AgentWorker",
    "Roster",
    "StaffedAgent",
    "ToolBox",
    "ToolCall",
    "ToolResult",
    "TurnResult",
    "ViewContext",
    "build_view",
    "install_guards",
    "register_handler",
    "register_tool",
    "register_view",
    "registered_tools",
    "registered_views",
    "verify_guards",
]
