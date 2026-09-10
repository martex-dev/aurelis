"""Mechanisms: the join that turns a mined conjunction into a tested scheme.

The world model (M29) can find co-occurrences — a volume spike then a range
break on the same instrument within a day, thirty-seven times on BTC-USD. The
judgement seat (M25) can score a forward view. Neither, alone, is a discovery.
The brief is explicit about the critical design point:

    A mined pattern is not a discovery. It becomes one only when an agent can
    state a mechanism — why this would work, who is on the other side, what
    constraint or asymmetry makes it persist — and that mechanism must generate
    additional predictions beyond the one it was found on. Test those
    separately.

This package is that join. An agent is shown a co-occurrence and states a
**mechanism**: the pattern in words, why it works, who is on the other side,
and a decay model — how crowded it can get and how fast it dies once others
find it. The mechanism implies a rule: *when the trigger event fires, the
instrument moves this way over this horizon.* That rule is then applied to
**every other occurrence** of the trigger, each sealed as a forward prediction
before its outcome exists, scored through the same resolver M25 already runs.

The occurrence the mechanism was found on is the training instance and is
excluded from its score. A mechanism whose out-of-sample predictions are
calibrated — better than a coin toss and better than the base rate — is a
candidate scheme. One whose predictions are noise is retired to the graveyard
and kept there, because a mechanism that failed is the most valuable thing the
company can show that it will not fool itself.

Statistics alone cannot separate a scheme from a coincidence when the events
are rare and the hypothesis space is unbounded. Requiring a mechanism, and
then testing what else the mechanism implies, can. That is the whole point.
"""

from aurelis.mechanism.library import Mechanisms, MechanismStatus
from aurelis.mechanism.predictions import generate_predictions

__all__ = ["MechanismStatus", "Mechanisms", "generate_predictions"]
