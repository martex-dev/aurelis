"""The rule language: grammar, parser, canonical form, and evaluator.

A rule is a list of clauses, read top to bottom. The first clause whose
condition holds decides the position for that bar; if none holds, the default
(``flat`` unless an ``else`` clause says otherwise) applies.

.. code-block:: text

    ret(24) > 0.02 and vol(72) < 0.01 -> long
    ret(24) < -0.02                    -> short
    else                               -> flat

Conditions compare arithmetic over features. Features are functions of the
closes up to and including the current bar and nothing else:

======== ====================================================================
feature  meaning
======== ====================================================================
close    the current close
ret(n)   close / close n bars ago, minus one
sma(n)   mean of the last n closes
ema(n)   exponential mean of closes, span n, seeded by the first n closes
vol(n)   standard deviation of the last n one-bar returns
high(n)  highest close of the last n bars
low(n)   lowest close of the last n bars
rsi(n)   Wilder's relative strength index over n bars, in [0, 100]
======== ====================================================================

Everything is exact decimal arithmetic. A bar inside a feature's warm-up has no
value for that feature, and a comparison with no value is false, so the rule
falls through to the next clause. The program's warm-up is the longest window
it references, and the engine trades nothing inside it.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any

from aurelis.core.canonical import sha256_of

__all__ = [
    "FEATURES",
    "MAX_CLAUSES",
    "MAX_TEXT",
    "MAX_WINDOW",
    "POSITIONS",
    "REFERENCE",
    "Program",
    "RuleSyntaxError",
    "evaluate",
    "parse",
    "render",
]

FEATURES: dict[str, bool] = {
    "close": False,
    "ret": True,
    "sma": True,
    "ema": True,
    "vol": True,
    "high": True,
    "low": True,
    "rsi": True,
}
"""Feature name to whether it takes a window. A closed set."""

POSITIONS: tuple[str, ...] = ("long", "short", "flat")
MAX_WINDOW = 720
MAX_CLAUSES = 8
MAX_TEXT = 1500
_COMPARISONS = (">=", "<=", ">", "<")
_ZERO = Decimal(0)
_ONE = Decimal(1)
_Q = Decimal("0.00000001")

REFERENCE = (
    "One clause per line, read top to bottom; the first clause whose condition "
    "holds decides the bar. Form: <condition> -> long | short | flat. An "
    "optional final line `else -> <position>` sets the default, otherwise flat.\n"
    "Features, each a function of closes up to the current bar only: close; "
    "ret(n) = close over close n bars ago minus one; sma(n) mean of last n "
    "closes; ema(n) exponential mean with span n; vol(n) standard deviation of "
    "the last n one-bar returns; high(n) and low(n) highest and lowest close of "
    "the last n bars; rsi(n) Wilder RSI in 0 to 100. Windows n are whole numbers "
    f"from 1 to {MAX_WINDOW}.\n"
    "Conditions compare arithmetic (+ - * /) over features and numbers with > < "
    ">= <=, joined by and, or, not, and parentheses. Numbers are decimals such "
    f"as 0.02. At most {MAX_CLAUSES} clauses. Nothing else is available: no "
    "volume, no other instruments, no state between bars."
)
"""What the agent is told about the language. Shown in the material."""


class RuleSyntaxError(ValueError):
    """The text is not a rule. Says where and why."""

    def __init__(self, message: str, *, line: int | None = None) -> None:
        where = f"line {line}: " if line is not None else ""
        super().__init__(f"{where}{message}")
        self.line = line


# ------------------------------------------------------------------ tokens

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<name>[A-Za-z_]+)|(?P<op>->|>=|<=|>|<|[+\-*/(),]))"
)


def _tokens(text: str, line: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    stripped = text.rstrip()
    while pos < len(stripped):
        match = _TOKEN.match(stripped, pos)
        if match is None or match.end() == pos:
            raise RuleSyntaxError(f"unexpected character {stripped[pos]!r}", line=line)
        pos = match.end()
        if match.group("num") is not None:
            out.append(("num", match.group("num")))
        elif match.group("name") is not None:
            out.append(("name", match.group("name").lower()))
        else:
            out.append(("op", match.group("op")))
    return out


# ------------------------------------------------------------------ parser


class _Parser:
    """Recursive descent over one clause's tokens."""

    def __init__(self, tokens: list[tuple[str, str]], line: int) -> None:
        self.tokens = tokens
        self.pos = 0
        self.line = line

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise RuleSyntaxError("unexpected end of clause", line=self.line)
        self.pos += 1
        return token

    def accept(self, kind: str, value: str) -> bool:
        token = self.peek()
        if token == (kind, value):
            self.pos += 1
            return True
        return False

    def expect(self, kind: str, value: str) -> None:
        if not self.accept(kind, value):
            got = self.peek()
            raise RuleSyntaxError(
                f"expected {value!r}, got {got[1] if got else 'end of clause'!r}",
                line=self.line,
            )

    # condition := or
    def condition(self) -> dict[str, Any]:
        left = self.conjunction()
        while self.accept("name", "or"):
            left = {"bool": "or", "left": left, "right": self.conjunction()}
        return left

    def conjunction(self) -> dict[str, Any]:
        left = self.negation()
        while self.accept("name", "and"):
            left = {"bool": "and", "left": left, "right": self.negation()}
        return left

    def negation(self) -> dict[str, Any]:
        if self.accept("name", "not"):
            return {"bool": "not", "arg": self.negation()}
        if self.peek() == ("op", "("):
            # Either a parenthesised condition or a parenthesised arithmetic
            # term at the head of a comparison. Try the condition first and
            # fall back, because the two share a first token.
            saved = self.pos
            try:
                self.take()
                inner = self.condition()
                self.expect("op", ")")
                following = self.peek()
                if following is not None and following[1] in (
                    *_COMPARISONS,
                    "+",
                    "-",
                    "*",
                    "/",
                ):
                    raise RuleSyntaxError("comparison after a condition", line=self.line)
                return inner
            except RuleSyntaxError:
                self.pos = saved
        return self.comparison()

    def comparison(self) -> dict[str, Any]:
        left = self.arith()
        token = self.peek()
        if token is None or token[0] != "op" or token[1] not in _COMPARISONS:
            raise RuleSyntaxError(
                "a condition must compare two values with > < >= or <=", line=self.line
            )
        self.take()
        return {"cmp": token[1], "left": left, "right": self.arith()}

    def arith(self) -> dict[str, Any]:
        left = self.term()
        while True:
            token = self.peek()
            if token is not None and token[0] == "op" and token[1] in ("+", "-"):
                self.take()
                left = {"op": token[1], "left": left, "right": self.term()}
            else:
                return left

    def term(self) -> dict[str, Any]:
        left = self.factor()
        while True:
            token = self.peek()
            if token is not None and token[0] == "op" and token[1] in ("*", "/"):
                self.take()
                left = {"op": token[1], "left": left, "right": self.factor()}
            else:
                return left

    def factor(self) -> dict[str, Any]:
        kind, value = self.take()
        if kind == "num":
            return {"num": str(Decimal(value).normalize()) if "." in value else value}
        if kind == "op" and value == "-":
            return {"op": "neg", "arg": self.factor()}
        if kind == "op" and value == "(":
            inner = self.arith()
            self.expect("op", ")")
            return inner
        if kind == "name":
            if value not in FEATURES:
                raise RuleSyntaxError(
                    f"{value!r} is not a feature; the features are {', '.join(FEATURES)}",
                    line=self.line,
                )
            if not FEATURES[value]:
                return {"feat": value}
            self.expect("op", "(")
            window_kind, window = self.take()
            if window_kind != "num" or "." in window:
                raise RuleSyntaxError(f"{value} needs a whole-number window", line=self.line)
            n = int(window)
            if not 1 <= n <= MAX_WINDOW:
                raise RuleSyntaxError(
                    f"{value}({n}): windows run from 1 to {MAX_WINDOW}", line=self.line
                )
            self.expect("op", ")")
            return {"feat": value, "n": n}
        raise RuleSyntaxError(f"unexpected {value!r}", line=self.line)


@dataclass(frozen=True, slots=True)
class Program:
    """A parsed rule: what runs, what it hashes to, and what it needs."""

    clauses: tuple[tuple[dict[str, Any], str], ...]
    default: str
    source: str
    """What the agent actually wrote, kept beside the canonical form."""

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "clauses": [{"when": when, "position": position} for when, position in self.clauses],
            "default": self.default,
        }

    @property
    def digest(self) -> str:
        """Over the canonical structure, so whitespace and spelling of the
        same rule do not make two rules."""
        return sha256_of(self.payload)

    @property
    def windows(self) -> tuple[int, ...]:
        found: set[int] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if "n" in node:
                    found.add(int(node["n"]))
                for value in node.values():
                    walk(value)

        for when, _ in self.clauses:
            walk(when)
        return tuple(sorted(found))

    @property
    def warmup(self) -> int:
        """Bars before every feature has a value. The engine trades none of them."""
        return max(self.windows, default=0)

    @property
    def uses_short(self) -> bool:
        return any(position == "short" for _, position in self.clauses) or self.default == "short"

    @property
    def text(self) -> str:
        return render(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, source: str = "") -> Program:
        clauses = tuple((dict(item["when"]), str(item["position"])) for item in payload["clauses"])
        program = cls(clauses=clauses, default=str(payload["default"]), source=source)
        _check(program)
        return program


def _check(program: Program) -> None:
    if not program.clauses:
        raise RuleSyntaxError("a rule needs at least one clause")
    if len(program.clauses) > MAX_CLAUSES:
        raise RuleSyntaxError(f"at most {MAX_CLAUSES} clauses; this has {len(program.clauses)}")
    for _, position in program.clauses:
        if position not in POSITIONS:
            raise RuleSyntaxError(f"{position!r} is not a position; use long, short or flat")
    if program.default not in POSITIONS:
        raise RuleSyntaxError(f"{program.default!r} is not a position")
    if all(position == "flat" for _, position in program.clauses) and program.default == "flat":
        raise RuleSyntaxError("every clause is flat; the rule never trades")


def parse(text: str) -> Program:
    """Text to :class:`Program`, or :class:`RuleSyntaxError`. Never a guess."""
    if len(text) > MAX_TEXT:
        raise RuleSyntaxError(f"a rule is at most {MAX_TEXT} characters")
    clauses: list[tuple[dict[str, Any], str]] = []
    default = "flat"
    saw_default = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if saw_default:
            raise RuleSyntaxError("nothing may follow the else clause", line=number)
        if "->" not in line:
            raise RuleSyntaxError("a clause is <condition> -> <position>", line=number)
        head, _, tail = line.rpartition("->")
        position = tail.strip().lower()
        if position not in POSITIONS:
            raise RuleSyntaxError(
                f"{position!r} is not a position; use long, short or flat", line=number
            )
        head = head.strip()
        if head.lower() == "else":
            default = position
            saw_default = True
            continue
        parser = _Parser(_tokens(head, number), number)
        condition = parser.condition()
        if parser.peek() is not None:
            trailing = parser.peek()
            assert trailing is not None
            raise RuleSyntaxError(f"unexpected {trailing[1]!r}", line=number)
        clauses.append((condition, position))
    program = Program(clauses=tuple(clauses), default=default, source=text)
    _check(program)
    return program


# ------------------------------------------------------------------ rendering


def _render_expr(node: dict[str, Any]) -> str:
    if "num" in node:
        return str(node["num"])
    if "feat" in node:
        return node["feat"] if "n" not in node else f"{node['feat']}({node['n']})"
    if "op" in node:
        if node["op"] == "neg":
            return f"-{_render_expr(node['arg'])}"
        return f"({_render_expr(node['left'])} {node['op']} {_render_expr(node['right'])})"
    if "cmp" in node:
        return f"{_render_expr(node['left'])} {node['cmp']} {_render_expr(node['right'])}"
    if "bool" in node:
        if node["bool"] == "not":
            return f"not ({_render_expr(node['arg'])})"
        return f"({_render_expr(node['left'])} {node['bool']} {_render_expr(node['right'])})"
    raise RuleSyntaxError(f"unrenderable node {node!r}")


def render(program: Program) -> str:
    """Canonical text. Parsing it again gives the same digest."""
    lines = [f"{_render_expr(when)} -> {position}" for when, position in program.clauses]
    if program.default != "flat":
        lines.append(f"else -> {program.default}")
    return "\n".join(lines)


# ------------------------------------------------------------------ features


def _sqrt(value: Decimal) -> Decimal:
    return value.sqrt() if value > _ZERO else _ZERO


def _ret(closes: list[Decimal], n: int) -> list[Decimal | None]:
    return [
        (closes[t] / closes[t - n] - _ONE) if t >= n and closes[t - n] else None
        for t in range(len(closes))
    ]


def _sma(closes: list[Decimal], n: int) -> list[Decimal | None]:
    out: list[Decimal | None] = []
    running = _ZERO
    for t, close in enumerate(closes):
        running += close
        if t >= n:
            running -= closes[t - n]
        out.append((running / n) if t >= n - 1 else None)
    return out


def _ema(closes: list[Decimal], n: int) -> list[Decimal | None]:
    out: list[Decimal | None] = []
    alpha = Decimal(2) / Decimal(n + 1)
    value: Decimal | None = None
    running = _ZERO
    for t, close in enumerate(closes):
        if t < n - 1:
            running += close
            out.append(None)
            continue
        if value is None:
            running += close
            value = running / n
        else:
            value = alpha * close + (_ONE - alpha) * value
        out.append(value)
    return out


def _vol(closes: list[Decimal], n: int) -> list[Decimal | None]:
    returns: list[Decimal] = [
        (closes[t] / closes[t - 1] - _ONE) if closes[t - 1] else _ZERO
        for t in range(1, len(closes))
    ]
    out: list[Decimal | None] = [None]
    total = _ZERO
    squares = _ZERO
    for i, r in enumerate(returns):
        total += r
        squares += r * r
        if i >= n:
            gone = returns[i - n]
            total -= gone
            squares -= gone * gone
        if i >= n - 1:
            mean = total / n
            variance = squares / n - mean * mean
            out.append(_sqrt(variance if variance > _ZERO else _ZERO))
        else:
            out.append(None)
    return out


def _extreme(closes: list[Decimal], n: int, *, highest: bool) -> list[Decimal | None]:
    out: list[Decimal | None] = []
    window: deque[int] = deque()
    for t, close in enumerate(closes):
        while window and (closes[window[-1]] <= close if highest else closes[window[-1]] >= close):
            window.pop()
        window.append(t)
        if window[0] <= t - n:
            window.popleft()
        out.append(closes[window[0]] if t >= n - 1 else None)
    return out


def _rsi(closes: list[Decimal], n: int) -> list[Decimal | None]:
    out: list[Decimal | None] = [None]
    gain: Decimal | None = None
    loss: Decimal | None = None
    gains = _ZERO
    losses = _ZERO
    for t in range(1, len(closes)):
        change = closes[t] - closes[t - 1]
        up = change if change > _ZERO else _ZERO
        down = -change if change < _ZERO else _ZERO
        if t <= n:
            gains += up
            losses += down
            if t < n:
                out.append(None)
                continue
            gain, loss = gains / n, losses / n
        else:
            assert gain is not None and loss is not None
            gain = (gain * (n - 1) + up) / n
            loss = (loss * (n - 1) + down) / n
        if loss == _ZERO:
            out.append(Decimal(100))
        else:
            rs = gain / loss
            out.append(Decimal(100) - Decimal(100) / (_ONE + rs))
    return out


def _features(
    program: Program, closes: list[Decimal]
) -> dict[tuple[str, int], list[Decimal | None]]:
    needed: set[tuple[str, int]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "feat" in node:
                needed.add((str(node["feat"]), int(node.get("n", 0))))
            for value in node.values():
                walk(value)

    for when, _ in program.clauses:
        walk(when)

    table: dict[tuple[str, int], list[Decimal | None]] = {}
    for name, n in needed:
        if name == "close":
            table[(name, 0)] = list(closes)
        elif name == "ret":
            table[(name, n)] = _ret(closes, n)
        elif name == "sma":
            table[(name, n)] = _sma(closes, n)
        elif name == "ema":
            table[(name, n)] = _ema(closes, n)
        elif name == "vol":
            table[(name, n)] = _vol(closes, n)
        elif name == "high":
            table[(name, n)] = _extreme(closes, n, highest=True)
        elif name == "low":
            table[(name, n)] = _extreme(closes, n, highest=False)
        elif name == "rsi":
            table[(name, n)] = _rsi(closes, n)
    return table


# ------------------------------------------------------------------ evaluation


def _value(
    node: dict[str, Any], table: dict[tuple[str, int], list[Decimal | None]], t: int
) -> Decimal | None:
    if "num" in node:
        return Decimal(str(node["num"]))
    if "feat" in node:
        return table[(str(node["feat"]), int(node.get("n", 0)))][t]
    if "op" in node:
        if node["op"] == "neg":
            arg = _value(node["arg"], table, t)
            return None if arg is None else -arg
        left = _value(node["left"], table, t)
        right = _value(node["right"], table, t)
        if left is None or right is None:
            return None
        try:
            if node["op"] == "+":
                return left + right
            if node["op"] == "-":
                return left - right
            if node["op"] == "*":
                return left * right
            return left / right
        except (DivisionByZero, InvalidOperation):
            return None
    raise RuleSyntaxError(f"not a value: {node!r}")


def _holds(
    node: dict[str, Any], table: dict[tuple[str, int], list[Decimal | None]], t: int
) -> bool:
    if "cmp" in node:
        left = _value(node["left"], table, t)
        right = _value(node["right"], table, t)
        if left is None or right is None:
            return False
        op = node["cmp"]
        if op == ">":
            return left > right
        if op == "<":
            return left < right
        if op == ">=":
            return left >= right
        return left <= right
    if "bool" in node:
        if node["bool"] == "not":
            return not _holds(node["arg"], table, t)
        if node["bool"] == "and":
            return _holds(node["left"], table, t) and _holds(node["right"], table, t)
        return _holds(node["left"], table, t) or _holds(node["right"], table, t)
    raise RuleSyntaxError(f"not a condition: {node!r}")


_WEIGHT = {"long": _ONE, "short": Decimal(-1), "flat": _ZERO}


def evaluate(program: Program, closes: list[Decimal]) -> list[Decimal]:
    """The position the rule wants at every bar, from that bar's past only.

    Bars inside the warm-up are flat whatever the clauses say: a feature with
    no value cannot hold a comparison, and a rule that traded on a feature it
    had not yet computed would be trading on nothing.
    """
    table = _features(program, closes)
    out: list[Decimal] = []
    for t in range(len(closes)):
        if t < program.warmup:
            out.append(_ZERO)
            continue
        position = program.default
        for when, chosen in program.clauses:
            if _holds(when, table, t):
                position = chosen
                break
        out.append(_WEIGHT[position])
    return out
