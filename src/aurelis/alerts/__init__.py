"""Alerts: what needs attention, and whether anyone gave it.

Acknowledgement and resolution are separate acts with separate timestamps, so
"somebody looked" and "somebody fixed it" never collapse into one field. Open
alerts deduplicate while unresolved, because a monitoring system whose main
effect is to train people to ignore it is worse than none.
"""

from aurelis.alerts.service import Alerts, Severity
from aurelis.alerts.tables import Alert

__all__ = ["Alert", "Alerts", "Severity"]
