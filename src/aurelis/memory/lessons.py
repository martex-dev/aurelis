"""Lessons, and the few that become rules.

A retrospective that concludes something and writes it nowhere has produced
nothing. But the opposite failure is worse and much more common: an
organisation that promotes every observation into a binding rule, until the
rulebook forbids everything and everybody routes around it.

So the two are separated. A **lesson** is what somebody concluded, with the
record it came from. A **standing rule** is a lesson that binds future work,
and promoting one is a deliberate act with an author's name on it — never a
side effect of writing the lesson down.

Three properties follow from that split:

*A lesson with no source is an opinion.* ``source_ref`` is required, and it
points at the retrospective, meeting or finding that produced it. "We learned
X" is only checkable if a reader can go and see what happened.

*Rules can be retired.* A rule written after one bad quarter that is still
being enforced three regimes later is a liability, and the only defence is that
retiring one is as ordinary an act as writing one. Retirement keeps the row and
records the reason; nothing is deleted, because "why did we stop believing
this?" is a question the corpus should be able to answer.

*Rules are scoped.* ``applies_to`` names families or desks. A rule learned on
one desk that silently governs all seven is how a specific finding becomes
institutional superstition.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.memory.tables import Lesson
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["Lessons", "StandingRules"]


@dataclass(frozen=True, slots=True)
class StandingRules:
    """The rules that bind a particular piece of work, and why.

    Returned as a bundle rather than a list of strings so a brief can say
    *which* rule applies and where it came from. A constraint quoted without
    its source is indistinguishable from a preference.
    """

    scope: str
    rules: tuple[Lesson, ...]

    def as_payload(self) -> list[dict[str, str]]:
        return [
            {
                "ref": rule.ref,
                "rule": rule.statement,
                "from": rule.source_ref or "",
                "applies_to": ", ".join(str(item) for item in rule.applies_to),
            }
            for rule in self.rules
        ]

    def describe(self) -> str:
        if not self.rules:
            return f"no standing rules bind {self.scope}"
        lines = [f"{len(self.rules)} standing rule(s) bind {self.scope}:"]
        lines.extend(
            f"  {rule.ref} — {rule.statement} (from {rule.source_ref})"
            for rule in self.rules
        )
        return "\n".join(lines)


class Lessons:
    """Recording what was learned, and promoting the few that should bind."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def record(
        self,
        session: Session,
        *,
        statement: str,
        source_ref: str,
        author: str,
        standing_rule: bool = False,
        applies_to: tuple[str, ...] = (),
        at: dt.datetime | None = None,
    ) -> Lesson:
        """Write down what was learned.

        ``source_ref`` is mandatory and unenforceable by a database constraint —
        it can point at a meeting, a finding, a mission or a run, and a foreign
        key would have to choose one. So it is checked here, and the check is
        that it is *present*: a lesson nobody can trace is an assertion.
        """
        if not source_ref.strip():
            raise IntegrityViolation(
                "a lesson must cite where it came from; one that does not is an "
                "opinion with a reference number"
            )
        if standing_rule and not applies_to:
            raise IntegrityViolation(
                "a standing rule must name what it applies to. A rule with "
                "unlimited scope binds every desk and every family, which is "
                "how one desk's finding becomes the whole company's superstition"
            )

        moment = at or self._clock.now()
        ref = allocate_ref(session, RefKind.LESSON)
        lesson = Lesson(
            lesson_id=uuid7(),
            ref=ref,
            statement=statement,
            source_ref=source_ref,
            standing_rule=standing_rule,
            applies_to=list(applies_to),
            author=author,
            created_at=moment,
        )
        session.add(lesson)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.LESSON_RECORDED,
            actor=author,
            subject=ref,
            payload={
                "author": author,
                "source_ref": source_ref,
                "standing_rule": standing_rule,
                "applies_to": list(applies_to),
                "statement": statement[:400],
            },
            at=moment,
        )
        return lesson

    def retire(
        self,
        session: Session,
        ref: str,
        *,
        reason: str,
        at: dt.datetime | None = None,
    ) -> Lesson:
        """Stop a rule binding future work, keeping the row and the reason.

        Retirement, not deletion. A rule that was enforced for two years and
        then dropped is part of the company's history, and a corpus that
        removed it could not explain decisions made while it was in force.
        """
        if not reason.strip():
            raise IntegrityViolation(
                "retiring a rule requires a reason; an unexplained retirement "
                "cannot be distinguished from someone finding it inconvenient"
            )
        moment = at or self._clock.now()
        lesson = session.execute(
            sa.select(Lesson).where(Lesson.ref == ref)
        ).scalar_one()
        if lesson.retired_at is not None:
            return lesson

        lesson.retired_at = moment
        lesson.retired_reason = reason
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.LESSON_RETIRED,
            actor=Actor.OPERATOR,
            subject=ref,
            payload={"reason": reason, "was_standing_rule": lesson.standing_rule},
            at=moment,
        )
        return lesson

    def binding(
        self, session: Session, *, family: str = "", desk: str | None = None
    ) -> StandingRules:
        """The live rules that apply to a family or desk.

        Matching is by family *prefix*, so a rule on ``strategy.momentum``
        binds ``strategy.momentum.crypto`` without anybody having to enumerate
        the subtree. A rule scoped to ``*`` binds everything and is meant to be
        rare enough to notice.
        """
        scope = family or (desk or "everything")
        candidates = session.execute(
            sa.select(Lesson).where(
                Lesson.standing_rule.is_(True),
                Lesson.retired_at.is_(None),
            )
        ).scalars()

        matched = [
            rule
            for rule in candidates
            if _applies(rule, family=family, desk=desk)
        ]
        matched.sort(key=lambda rule: rule.ref)
        return StandingRules(scope=scope, rules=tuple(matched))

    def live(self, session: Session) -> list[Lesson]:
        """Every lesson still standing, newest first."""
        return list(
            session.execute(
                sa.select(Lesson)
                .where(Lesson.retired_at.is_(None))
                .order_by(Lesson.created_at.desc())
            ).scalars()
        )


def _applies(rule: Lesson, *, family: str, desk: str | None) -> bool:
    for raw in rule.applies_to:
        target = str(raw)
        if target == "*":
            return True
        if desk and target == desk:
            return True
        if family and (family == target or family.startswith(f"{target}.")):
            return True
    return False
