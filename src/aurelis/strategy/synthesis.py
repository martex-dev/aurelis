"""Authoring components and composing them into strategies.

This is the module the whole project turns on, so it is worth being blunt about
what it refuses to do.

**There is no function that turns a hypothesis into a strategy.** Not
``promote``, not ``from_hypothesis``, not a foreign key from
``strategy_versions`` to ``hypotheses``. A company that could promote its best
result would be a selection engine: it would produce whatever the corpus
already contained and stop the day the corpus ran out. What exists instead is
:func:`author_component` and :func:`compose` — agents write pieces, with stated
reasoning and a cited origin, and a strategy is what those pieces make.

A refuted hypothesis is still enormously useful, but as *material*, not as a
candidate. ``Origin.DERIVED_FROM_FAILURE`` is a component that answers a
specific failure, citing it, and it is the most valuable origin in the
taxonomy: it is what a graveyard is for.

**Novelty is measured, not claimed.** :func:`novelty` reports what fraction of
a composition the company authored versus inherited, by counting origins. A
version assembled entirely from ``ADAPTED`` components reads as inheritance —
honestly, on its own page — and the company can see whether it is actually
inventing anything or just recombining somebody else's work.

**Every origin must be citable, and the citation shape is checked.** An
``INVENTED`` component names the meeting or task where the invention happened;
``DERIVED_FROM_FAILURE`` names the hypothesis it answers; ``ADAPTED`` names the
inherited trial. Without that, "we created this" is unfalsifiable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.org.desks import Desk
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.chain import payload_hash
from aurelis.platform.ledger.ledger import Ledger
from aurelis.strategy.markets import unknown_assumptions, unmet_assumptions
from aurelis.strategy.states import (
    ComponentKind,
    Origin,
    Portability,
    StrategyState,
)
from aurelis.strategy.tables import (
    Component,
    Strategy,
    StrategyLineage,
    StrategyPortability,
    StrategyVersion,
    VersionComponent,
)

__all__ = [
    "Composition",
    "Novelty",
    "Synthesis",
]

_CITATION_PREFIXES: dict[Origin, tuple[str, ...]] = {
    Origin.INVENTED: ("MTG-", "TSK-", "KCK-", "RTR-"),
    Origin.DERIVED_FROM_FAILURE: ("HYP-", "FND-", "OBJ-"),
    Origin.ADAPTED: ("MQ-", "HYP-", "LSN-"),
    Origin.REFINED: ("CMP-",),
    Origin.COMBINED: ("CMP-",),
}
"""What each origin must cite.

The shapes are checked because an origin nobody can follow is decoration. An
``INVENTED`` component citing a corpus trial is not invented, and the mismatch
is exactly the kind of thing that becomes invisible once it is prose.
"""


@dataclass(frozen=True, slots=True)
class Composition:
    """A version and what it was made of."""

    version: StrategyVersion
    components: tuple[Component, ...]
    lineage: tuple[StrategyLineage, ...]

    def describe(self) -> str:
        parts = ", ".join(f"{c.ref}:{c.kind}" for c in self.components)
        return f"{self.version.ref} composed from {parts}"


@dataclass(frozen=True, slots=True)
class Novelty:
    """How much of a composition the company actually authored.

    Reported rather than judged. There is no threshold here and no pass/fail:
    a version built mostly from adapted work is not wrong, it is *inherited*,
    and the point is that the reader can tell.
    """

    version_ref: str
    total: int
    by_origin: dict[str, int]

    @property
    def authored(self) -> int:
        """Components this company wrote, rather than took."""
        return (
            self.by_origin.get(Origin.INVENTED.value, 0)
            + self.by_origin.get(Origin.DERIVED_FROM_FAILURE.value, 0)
        )

    @property
    def inherited(self) -> int:
        return self.by_origin.get(Origin.ADAPTED.value, 0)

    def describe(self) -> str:
        if not self.total:
            return f"{self.version_ref}: no components"
        breakdown = ", ".join(
            f"{count} {origin}" for origin, count in sorted(self.by_origin.items())
        )
        return (
            f"{self.version_ref}: {self.authored} of {self.total} component(s) "
            f"authored here, {self.inherited} inherited ({breakdown})"
        )


class Synthesis:
    """Authoring, composing, mutating. The company's creative surface."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # ---------------------------------------------------------- authoring

    def author_component(
        self,
        session: Session,
        *,
        kind: ComponentKind,
        name: str,
        spec: dict[str, Any],
        rationale: str,
        origin: Origin,
        origin_ref: str,
        author: str,
        desk: Desk,
        assumes: tuple[str, ...] = (),
        at: dt.datetime | None = None,
    ) -> Component:
        """Write a new piece of a strategy.

        The rationale is required and must be substantive: a component is a
        claim about why something should work, and one with no stated reasoning
        is a parameter somebody tried. The origin citation is checked for
        shape, so "invented" cannot quietly mean "copied".
        """
        if len(rationale.strip()) < 20:
            raise IntegrityViolation(
                "a component must state why it should work, in the author's own "
                "words. A component with no reasoning is a parameter somebody "
                "tried, and it cannot be argued with later"
            )
        self._check_citation(origin, origin_ref)

        unknown = unknown_assumptions(assumes)
        if unknown:
            raise IntegrityViolation(
                f"{name} declares assumptions the market model does not know: "
                f"{', '.join(unknown)}. An assumption nothing can check would "
                "make the portability check look more complete than it is"
            )

        moment = at or self._clock.now()
        ref = allocate_ref(session, RefKind.COMPONENT)
        component = Component(
            component_id=uuid7(),
            ref=ref,
            kind=kind.value,
            name=name,
            spec=dict(spec),
            spec_digest=payload_hash(dict(spec)),
            rationale=rationale,
            origin=origin.value,
            origin_ref=origin_ref,
            author=author,
            desk=desk.value,
            assumes=list(assumes),
            created_at=moment,
        )
        session.add(component)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.COMPONENT_AUTHORED,
            actor=author,
            subject=ref,
            payload={
                "kind": kind.value,
                "name": name,
                "origin": origin.value,
                "origin_ref": origin_ref,
                "desk": desk.value,
                "assumes": list(assumes),
                "digest": component.spec_digest[:16],
            },
            at=moment,
        )
        return component

    @staticmethod
    def _check_citation(origin: Origin, origin_ref: str) -> None:
        if not origin_ref.strip():
            raise IntegrityViolation(
                f"an origin of {origin.value} must cite where it came from; "
                "an uncited origin makes 'we created this' unfalsifiable"
            )
        prefixes = _CITATION_PREFIXES[origin]
        if not origin_ref.startswith(prefixes):
            raise IntegrityViolation(
                f"an origin of {origin.value} must cite one of "
                f"{', '.join(prefixes)} — got {origin_ref!r}. An invented "
                "component citing inherited work is not invented"
            )

    # ---------------------------------------------------------- composing

    def open_strategy(
        self,
        session: Session,
        *,
        name: str,
        thesis: str,
        desk: Desk,
        owner: str,
        at: dt.datetime | None = None,
    ) -> Strategy:
        """Start a strategy at IDEA. A thesis is required to leave it."""
        moment = at or self._clock.now()
        ref = allocate_ref(session, RefKind.STRATEGY)
        strategy = Strategy(
            strategy_id=uuid7(),
            ref=ref,
            name=name,
            thesis=thesis,
            desk=desk.value,
            state=StrategyState.IDEA,
            owner_agent=owner,
            created_at=moment,
        )
        session.add(strategy)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.STRATEGY_OPENED,
            actor=owner,
            subject=ref,
            payload={"name": name, "desk": desk.value, "thesis": thesis[:300]},
            at=moment,
        )
        return strategy

    def compose(
        self,
        session: Session,
        *,
        strategy_ref: str,
        components: tuple[Component, ...],
        universe: dict[str, Any],
        cost_model: dict[str, Any],
        known_weaknesses: tuple[str, ...],
        author: str,
        constraints: dict[str, Any] | None = None,
        risk_assumptions: str = "",
        supersedes: str | None = None,
        change_reason: str = "",
        meeting_ref: str | None = None,
        at: dt.datetime | None = None,
    ) -> Composition:
        """Build a version out of authored components.

        Refuses a composition with no signal — a strategy without an idea in it
        is a sizing rule — and refuses one whose authors cannot name a
        weakness. Every composition has a regime it does not survive; one whose
        authors cannot say which has not looked.
        """
        moment = at or self._clock.now()
        strategy = self._strategy(session, strategy_ref)

        if not components:
            raise IntegrityViolation("a version must be composed of something")
        kinds = {component.kind for component in components}
        if ComponentKind.SIGNAL.value not in kinds:
            raise IntegrityViolation(
                "a version needs at least one signal component. A composition "
                "of filters and sizing rules has no idea in it"
            )
        if not known_weaknesses:
            raise IntegrityViolation(
                "a version must name at least one known weakness. Every "
                "composition has a regime it does not survive, and authors who "
                "cannot name one have not looked"
            )

        desk = Desk(strategy.desk)
        self._check_components_fit(desk, components)

        number = self._next_version_number(session, strategy_ref)
        ref = allocate_ref(session, RefKind.STRATEGY_VERSION)
        spec = {
            "components": [
                {"ref": c.ref, "kind": c.kind, "digest": c.spec_digest}
                for c in components
            ],
            "universe": dict(universe),
            "cost_model": dict(cost_model),
            "constraints": dict(constraints or {}),
        }

        version = StrategyVersion(
            version_id=uuid7(),
            ref=ref,
            strategy_ref=strategy_ref,
            n=number,
            spec=spec,
            spec_digest=payload_hash(spec),
            desk=strategy.desk,
            universe=dict(universe),
            cost_model=dict(cost_model),
            constraints=dict(constraints or {}),
            risk_assumptions=risk_assumptions,
            state=StrategyState.UNDER_REVIEW,
            evidence=[],
            known_weaknesses=list(known_weaknesses),
            supersedes=supersedes,
            change_reason=change_reason,
            material_change=supersedes is not None,
            created_by=author,
            created_at=moment,
        )
        session.add(version)
        session.flush()

        for position, component in enumerate(components):
            session.add(
                VersionComponent(
                    version_ref=ref,
                    component_ref=component.ref,
                    role=component.kind,
                    position=position,
                    weight=None,
                    created_at=moment,
                )
            )

        self._seed_portability(session, ref, desk, components, moment)
        lineage = self._record(
            session,
            version_ref=ref,
            act="composed" if supersedes is None else "mutated",
            parent_ref=supersedes,
            detail=(
                change_reason
                or f"composed from {len(components)} authored component(s)"
            ),
            author=author,
            meeting_ref=meeting_ref,
            at=moment,
        )
        strategy.current_version = ref
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.STRATEGY_VERSION_COMPOSED,
            actor=author,
            subject=ref,
            payload={
                "strategy": strategy_ref,
                "n": number,
                "components": [c.ref for c in components],
                "origins": sorted({c.origin for c in components}),
                "desk": strategy.desk,
                "digest": version.spec_digest[:16],
                "supersedes": supersedes,
            },
            at=moment,
        )
        return Composition(version, tuple(components), (lineage,))

    def mutate(
        self,
        session: Session,
        *,
        version_ref: str,
        replace: Component,
        with_component: Component,
        author: str,
        reason: str,
        meeting_ref: str | None = None,
        at: dt.datetime | None = None,
    ) -> Composition:
        """Swap one component for another, producing a new version.

        Always a new version, never an edit — including when the parent is not
        yet validated. Mutating in place would make the lineage a list of
        things that are no longer true.
        """
        if not reason.strip():
            raise IntegrityViolation(
                "a mutation must say what it is trying to fix; an unexplained "
                "change cannot be evaluated as an attempt at anything"
            )
        parent = self._version(session, version_ref)
        current = self.components_of(session, version_ref)
        if replace.ref not in {component.ref for component in current}:
            raise IntegrityViolation(
                f"{replace.ref} is not part of {version_ref}"
            )

        swapped = tuple(
            with_component if component.ref == replace.ref else component
            for component in current
        )
        return self.compose(
            session,
            strategy_ref=parent.strategy_ref,
            components=swapped,
            universe=dict(parent.universe),
            cost_model=dict(parent.cost_model),
            constraints=dict(parent.constraints),
            risk_assumptions=parent.risk_assumptions,
            known_weaknesses=tuple(str(item) for item in parent.known_weaknesses),
            author=author,
            supersedes=parent.ref,
            change_reason=f"replaced {replace.ref} with {with_component.ref}: {reason}",
            meeting_ref=meeting_ref,
            at=at,
        )

    # -------------------------------------------------------- portability

    def _seed_portability(
        self,
        session: Session,
        version_ref: str,
        native: Desk,
        components: tuple[Component, ...],
        moment: dt.datetime,
    ) -> None:
        """A row per desk, so an unmeasured market is explicit.

        Without this, "we have not tried it on equities" and "it works on
        equities" are both an absence of rows, and a reader cannot tell which.

        Structural impossibility is settled here rather than on a later call,
        because it is a pure function of the components and the desk registry
        and both are known now. A desk left reading ``UNPROVEN`` when the
        composition could never run there would invite somebody to go and test
        it, which is a waste at best and a meaningless number at worst.
        """
        for desk in Desk:
            if desk is native:
                status, reason = (
                    Portability.NATIVE.value,
                    "composed and measured on this desk",
                )
            else:
                blocking = self._blocking_assumptions(desk, components)
                status, reason = (
                    (Portability.INAPPLICABLE.value, "; ".join(blocking))
                    if blocking
                    else (Portability.UNPROVEN.value, "")
                )
            session.add(
                StrategyPortability(
                    version_ref=version_ref,
                    desk=desk.value,
                    status=status,
                    reason=reason,
                    assessed_at=moment if reason else None,
                )
            )
        session.flush()

    @staticmethod
    def _blocking_assumptions(
        desk: Desk, components: tuple[Component, ...]
    ) -> list[str]:
        blocking: list[str] = []
        for component in components:
            unmet = unmet_assumptions(
                desk, tuple(str(item) for item in component.assumes)
            )
            blocking.extend(f"{component.ref} assumes {item.value}" for item in unmet)
        return blocking

    def declare_inapplicable(
        self,
        session: Session,
        *,
        version_ref: str,
        desk: Desk,
        reason: str,
        at: dt.datetime | None = None,
    ) -> StrategyPortability:
        """Mark a desk structurally out of reach for this version."""
        row = session.get(StrategyPortability, (version_ref, desk.value))
        if row is None:
            raise IntegrityViolation(f"{version_ref} has no row for {desk.value}")
        row.status = Portability.INAPPLICABLE.value
        row.reason = reason
        row.assessed_at = at or self._clock.now()
        session.flush()
        return row

    def check_portability(
        self, session: Session, version_ref: str
    ) -> dict[Desk, tuple[str, str]]:
        """What is known about this version on each of the seven desks.

        Automatically downgrades a desk to ``INAPPLICABLE`` when a component's
        declared assumptions cannot hold there — a funding signal on a calendar
        market is not an untested idea, it is a category error, and reporting
        it as merely unproven would invite somebody to go and test it.
        """
        components = self.components_of(session, version_ref)
        result: dict[Desk, tuple[str, str]] = {}

        for desk in Desk:
            row = session.get(StrategyPortability, (version_ref, desk.value))
            if row is None:
                continue
            if row.status in (Portability.NATIVE.value, Portability.PORTED.value):
                result[desk] = (row.status, row.reason)
                continue

            blocking = self._blocking_assumptions(desk, components)
            if blocking:
                row.status = Portability.INAPPLICABLE.value
                row.reason = "; ".join(blocking)
                row.assessed_at = self._clock.now()
                session.flush()
            result[desk] = (row.status, row.reason)
        return result

    # ------------------------------------------------------------ reading

    def components_of(self, session: Session, version_ref: str) -> tuple[Component, ...]:
        refs = list(
            session.execute(
                sa.select(VersionComponent.component_ref)
                .where(VersionComponent.version_ref == version_ref)
                .order_by(VersionComponent.position)
            ).scalars()
        )
        if not refs:
            return ()
        rows = {
            component.ref: component
            for component in session.execute(
                sa.select(Component).where(Component.ref.in_(refs))
            ).scalars()
        }
        return tuple(rows[ref] for ref in refs if ref in rows)

    def novelty(self, session: Session, version_ref: str) -> Novelty:
        """Count origins. The measured answer to "did we create this?"."""
        components = self.components_of(session, version_ref)
        by_origin: dict[str, int] = {}
        for component in components:
            by_origin[component.origin] = by_origin.get(component.origin, 0) + 1
        return Novelty(version_ref, len(components), by_origin)

    def lineage_of(
        self, session: Session, version_ref: str
    ) -> tuple[StrategyLineage, ...]:
        return tuple(
            session.execute(
                sa.select(StrategyLineage)
                .where(StrategyLineage.version_ref == version_ref)
                .order_by(StrategyLineage.created_at)
            ).scalars()
        )

    def ancestry(self, session: Session, version_ref: str) -> tuple[str, ...]:
        """Every version this one descends from, oldest first."""
        chain: list[str] = []
        current: str | None = version_ref
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            row = session.execute(
                sa.select(StrategyVersion).where(StrategyVersion.ref == current)
            ).scalar_one_or_none()
            if row is None:
                break
            chain.append(row.ref)
            current = row.supersedes
        return tuple(reversed(chain))

    def strategy(self, session: Session, ref: str) -> Strategy:
        return self._strategy(session, ref)

    def version(self, session: Session, ref: str) -> StrategyVersion:
        return self._version(session, ref)

    # ------------------------------------------------------------ helpers

    def _record(
        self,
        session: Session,
        *,
        version_ref: str,
        act: str,
        parent_ref: str | None,
        detail: str,
        author: str,
        meeting_ref: str | None,
        at: dt.datetime,
    ) -> StrategyLineage:
        entry = StrategyLineage(
            entry_id=uuid7(),
            version_ref=version_ref,
            act=act,
            parent_ref=parent_ref,
            detail=detail,
            author=author,
            meeting_ref=meeting_ref,
            created_at=at,
        )
        session.add(entry)
        session.flush()
        return entry

    @staticmethod
    def _check_components_fit(desk: Desk, components: tuple[Component, ...]) -> None:
        problems: list[str] = []
        for component in components:
            unmet = unmet_assumptions(
                desk, tuple(str(item) for item in component.assumes)
            )
            problems.extend(
                f"{component.ref} assumes {item.value}, which {desk.value} does "
                "not provide"
                for item in unmet
            )
        if problems:
            raise IntegrityViolation(
                "components do not fit this desk: "
                + "; ".join(problems)
                + ". A crypto assumption applied to another market produces a "
                "number that means nothing while looking like a result"
            )

    @staticmethod
    def _next_version_number(session: Session, strategy_ref: str) -> int:
        highest = session.execute(
            sa.select(sa.func.max(StrategyVersion.n)).where(
                StrategyVersion.strategy_ref == strategy_ref
            )
        ).scalar()
        return int(highest or 0) + 1

    @staticmethod
    def _strategy(session: Session, ref: str) -> Strategy:
        row = session.execute(
            sa.select(Strategy).where(Strategy.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(f"no strategy {ref}")
        return row

    @staticmethod
    def _version(session: Session, ref: str) -> StrategyVersion:
        row = session.execute(
            sa.select(StrategyVersion).where(StrategyVersion.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(f"no strategy version {ref}")
        return row

