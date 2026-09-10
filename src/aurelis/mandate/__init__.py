"""M20 — the company decides whether it is ready, and asks.

The endpoint of this project is not a live adapter somebody switches on. It is
the company reaching the judgement itself, on evidence it gathered, and telling
the person who would have to fund it.

So there is a standard of eleven conditions, declared in advance and hashed; an
assessment that answers it in one of two words; and an escalation that fires
only on a yes. The refusals are recorded too, because a bar that was never seen
to hold is not a bar.

The honest first answer is **not yet**, and two of the conditions it misses
cannot be satisfied by any amount of research — no desk has a wired feed, and
nothing writes a replication record. Saying which is how the standard tells the
company what to build next.
"""

from aurelis.mandate.assessment import Finding, MandateOutcome, assess, history
from aurelis.mandate.standard import STANDARD, Criterion, digest

__all__ = [
    "STANDARD",
    "Criterion",
    "Finding",
    "MandateOutcome",
    "assess",
    "digest",
    "history",
]
