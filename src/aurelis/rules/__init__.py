"""Rules agents write, in a language the engine can run and the ledger can hash.

M15 gave an agent a menu of 72 designs and called the pick a strategy. The
brief for this stage says why that could never produce an idea only the agent
would have had, and says the menu has to go. This package is what replaces it:
a small, closed, deterministic language in which an agent **writes the rule**,
and an evaluator that runs it over bars with no state, no loops, no I/O and no
way to see the future.

Three properties make it a legitimate thing to hand an agent.

**It is total and hashable.** A rule parses to a canonical structure, the
structure hashes, and the hash is what a preregistration locks. Two rules that
mean the same thing hash the same whatever whitespace they were typed with.

**It cannot look ahead.** Every feature is a function of closes up to and
including the current bar, computed by sliding windows that never index
forward, and a test changes the future and asserts the past does not move.

**It is bounded.** At most eight clauses, windows of at most 720 bars, a
handful of features. Small enough to read in full, which is what makes a
rule reviewable by the critic and reproducible by someone who did not watch
it run — and large enough that an agent can say something the menu could not.

What it is not: a strategy language for schemes over events and entities. That
is the world model the brief describes, and it is not built here. This is the
mechanical-rule half of the two evidence regimes, and it stays inside the
preregistration and selection-correction machinery that exists for exactly that.
"""

from aurelis.rules.language import (
    FEATURES,
    MAX_CLAUSES,
    MAX_WINDOW,
    POSITIONS,
    REFERENCE,
    Program,
    RuleSyntaxError,
    evaluate,
    parse,
)

__all__ = [
    "FEATURES",
    "MAX_CLAUSES",
    "MAX_WINDOW",
    "POSITIONS",
    "REFERENCE",
    "Program",
    "RuleSyntaxError",
    "evaluate",
    "parse",
]
