"""Discriminating tests: how an argument ends in evidence.

This is the load-bearing mechanism of ADR-0002, and the reason meetings in this
company are not theatre.

An objection is not "I think this is overfit". An objection is a claim plus an
**executable specification that would settle it**: a registered tool, its
arguments, and an expectation about the result. The Chair dispatches it inside
the meeting, on the company's compute, and everyone sees the answer. Debate
then terminates because a measurement arrived, not because a token budget ran
out or somebody got tired.

The expectation is deliberately narrow — a field, a comparison, a value. Rich
enough to express "re-measure over a longer window and the change will still be
positive", too narrow to express a conclusion. A test that could assert
anything would just be the objection restated in a different font.

At M3 the available tools are data and descriptive statistics, so the tests
that can be posed are about measurement stability. The market taxonomy —
survivorship, look-ahead, understated costs — arrives at M5 with the engines
that can actually run those tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from aurelis.agents.tools import ToolBox
from aurelis.core.errors import PermissionDenied
from aurelis.org.scopes import ToolScope

__all__ = ["TestOutcome", "TestSpec", "dispatch", "parse_spec"]

_COMPARISONS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


@dataclass(frozen=True, slots=True)
class TestSpec:
    """An executable claim about what a tool will return.

    ``tool`` and ``arguments`` say what to run; ``field``, ``comparison`` and
    ``value`` say what the objector predicts. The objection is **upheld** when
    the prediction holds — an objector who says "the effect will vanish over a
    longer window" is right when it does.
    """

    tool: ToolScope
    arguments: dict[str, Any]
    field: str
    comparison: str
    value: Decimal
    describes: str = ""

    def describe(self) -> str:
        return (
            f"{self.tool.value}({self._render_arguments()}) -> "
            f"{self.field} {self.comparison} {self.value}"
        )

    def _render_arguments(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in sorted(self.arguments.items()))


@dataclass(frozen=True, slots=True)
class TestOutcome:
    """What happened when the test ran."""

    ran: bool
    upheld: bool
    observed: str | None
    detail: str
    context: dict[str, Any] = field(default_factory=dict)
    """Scalar fields the tool returned alongside the one being compared.

    Kept because a reader of the record needs to see *what the varied run
    actually was* -- how many instruments it traded, on what basis -- and not
    merely the single number that settled the objection.
    """

    def as_payload(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "upheld": self.upheld,
            "observed": self.observed,
            "detail": self.detail,
            **self.context,
        }


def parse_spec(payload: dict[str, Any]) -> TestSpec | None:
    """Read a test specification, returning ``None`` if it is not one.

    Refusing rather than guessing: a malformed spec means the objection is
    ``UNTESTABLE`` and gets reported as an unresolved limitation, which is a
    better outcome than a test that ran something nobody asked for.
    """
    try:
        tool = ToolScope(str(payload["tool"]))
        comparison = str(payload["comparison"])
        if comparison not in _COMPARISONS:
            return None
        return TestSpec(
            tool=tool,
            arguments=dict(payload.get("arguments") or {}),
            field=str(payload["field"]),
            comparison=comparison,
            value=Decimal(str(payload["value"])),
            describes=str(payload.get("describes", "")),
        )
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return None


def dispatch(
    session: Session,
    tools: ToolBox,
    spec: TestSpec,
    *,
    agent_ref: str,
    permitted: frozenset[ToolScope],
    meeting_ref: str,
) -> TestOutcome:
    """Run the test on the objector's own authority.

    Deliberately *not* on the Chair's authority. An objection that requires a
    capability its author does not hold is one the author could not have
    verified, and letting the Chair run it would launder the permission model
    through the meeting.
    """
    try:
        result = tools.invoke(
            session,
            agent_ref=agent_ref,
            scope=spec.tool,
            arguments=spec.arguments,
            permitted=permitted,
            task_ref=meeting_ref,
        )
    except PermissionDenied:
        return TestOutcome(
            ran=False,
            upheld=False,
            observed=None,
            detail=(
                f"{agent_ref} does not hold {spec.tool.value}; an objection "
                "requiring a capability its author lacks cannot be settled here"
            ),
        )
    except NotImplementedError as error:
        return TestOutcome(False, False, None, f"tool not available yet: {error}")
    except Exception as error:  # noqa: BLE001 - a failed test is an outcome
        return TestOutcome(False, False, None, f"{type(error).__name__}: {error}")

    observed = _extract(result.value, spec.field)
    if observed is None:
        return TestOutcome(
            ran=True,
            upheld=False,
            observed=None,
            detail=f"{spec.tool.value} returned no field {spec.field!r}",
        )

    try:
        measured = Decimal(str(observed))
    except InvalidOperation:
        return TestOutcome(
            ran=True,
            upheld=False,
            observed=str(observed),
            detail=f"{spec.field} is not numeric: {observed!r}",
        )

    holds = _COMPARISONS[spec.comparison](measured, spec.value)
    context = {
        key: value
        for key, value in (result.value or {}).items()
        if key != spec.field and isinstance(value, (str, int, float))
    }
    return TestOutcome(
        ran=True,
        upheld=bool(holds),
        observed=str(measured),
        detail=(
            f"measured {spec.field}={measured}; predicted {spec.comparison} "
            f"{spec.value} -> {'upheld' if holds else 'rejected'}"
        ),
        context=context,
    )


def _extract(payload: Any, field: str) -> Any:
    """Find ``field`` in a tool result, one level of nesting deep.

    Deliberately shallow. A path expression would let a test reach into
    structures the objector never saw, and the whole point is that the test
    checks something the room can also see.
    """
    if isinstance(payload, dict):
        if field in payload:
            return payload[field]
        for value in payload.values():
            if isinstance(value, dict) and field in value:
                return value[field]
    return None
