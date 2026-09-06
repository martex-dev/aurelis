"""Raising alerts, and recording whether anyone answered.

Deliberately small. The interesting property is not the raising — anything can
raise — but that acknowledgement and resolution are separate acts with separate
timestamps, so "somebody looked" and "somebody fixed it" never collapse into
one field.

Alerts deduplicate on ``(source, subject, severity)`` while unresolved. A
monitor firing every cycle should produce one open alert rather than a
thousand: an alert list nobody can read is an alert list nobody reads, and a
monitoring system whose main effect is to train people to ignore it is worse
than none.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.alerts.tables import Alert
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["Alerts", "Severity"]


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alerts:
    """Raise, acknowledge, resolve."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def raise_alert(
        self,
        session: Session,
        *,
        severity: Severity,
        source: str,
        message: str,
        recommended_action: str,
        raised_by: str,
        subject: str | None = None,
        desk: str | None = None,
        evidence: dict[str, Any] | None = None,
        at: dt.datetime | None = None,
    ) -> Alert:
        """Raise one, or return the open one that already says this."""
        if not recommended_action.strip():
            raise IntegrityViolation(
                "an alert must say what to do about it. One that only reports a "
                "problem hands the whole design task to whoever reads it at 3am"
            )
        moment = at or self._clock.now()

        subject_matches = (
            Alert.subject.is_(None) if subject is None else Alert.subject == subject
        )
        existing = session.execute(
            sa.select(Alert).where(
                Alert.source == source,
                subject_matches,
                Alert.severity == severity.value,
                Alert.resolved_at.is_(None),
            )
        ).scalars().first()
        if existing is not None:
            return existing

        ref = allocate_ref(session, RefKind.ALERT)
        alert = Alert(
            alert_id=uuid7(),
            ref=ref,
            severity=severity.value,
            source=source,
            subject=subject,
            desk=desk,
            message=message,
            recommended_action=recommended_action,
            evidence=dict(evidence or {}),
            raised_by=raised_by,
            raised_at=moment,
        )
        session.add(alert)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.ALERT_RAISED,
            actor=raised_by,
            subject=ref,
            payload={
                "severity": severity.value,
                "source": source,
                "about": subject,
                "message": message[:300],
                "recommended_action": recommended_action[:300],
            },
            at=moment,
        )
        return alert

    def acknowledge(
        self,
        session: Session,
        ref: str,
        *,
        by: str,
        at: dt.datetime | None = None,
    ) -> Alert:
        """Somebody looked. Distinct from having fixed it."""
        moment = at or self._clock.now()
        alert = self._alert(session, ref)
        if alert.acknowledged_at is None:
            alert.acknowledged_by = by
            alert.acknowledged_at = moment
            session.flush()
            self._ledger.append(
                session,
                kind=EventKind.ALERT_ACKNOWLEDGED,
                actor=by,
                subject=ref,
                payload={"severity": alert.severity, "source": alert.source},
                at=moment,
            )
        return alert

    def resolve(
        self,
        session: Session,
        ref: str,
        *,
        resolution: str,
        by: str,
        at: dt.datetime | None = None,
    ) -> Alert:
        """Somebody fixed it, and said what they did.

        Acknowledgement comes first — a CHECK enforces the ordering too.
        Resolving something nobody looked at is how an alert queue gets tidied
        instead of answered.
        """
        if not resolution.strip():
            raise IntegrityViolation("a resolution must say what was done")
        moment = at or self._clock.now()
        alert = self._alert(session, ref)
        if alert.acknowledged_at is None:
            self.acknowledge(session, ref, by=by, at=moment)
        alert.resolved_at = moment
        alert.resolution = resolution
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.ALERT_RESOLVED,
            actor=by,
            subject=ref,
            payload={"resolution": resolution[:300], "severity": alert.severity},
            at=moment,
        )
        return alert

    def open(self, session: Session) -> list[Alert]:
        return list(
            session.execute(
                sa.select(Alert)
                .where(Alert.resolved_at.is_(None))
                .order_by(Alert.severity, Alert.raised_at)
            ).scalars()
        )

    def unacknowledged(self, session: Session) -> list[Alert]:
        """Raised, and nobody has looked. The list that matters operationally."""
        return list(
            session.execute(
                sa.select(Alert)
                .where(Alert.acknowledged_at.is_(None))
                .order_by(Alert.raised_at)
            ).scalars()
        )

    @staticmethod
    def _alert(session: Session, ref: str) -> Alert:
        row = session.execute(
            sa.select(Alert).where(Alert.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(f"no alert {ref}")
        return row
