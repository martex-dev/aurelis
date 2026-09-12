# ADR-0039 — A mechanism may fire on the conjunction it was shown

Status: accepted · 2026-09-12

## Context

The miner shows an agent a *pair*: one kind of event followed by another
within a window, with the in-sample effect after the trigger. Every mechanism
stated through M37 then fired on the trigger alone. `MEC-0002` was shown
"volume spike then volume spike within 24h" and states a story about a
liquidation cascade running out of fuel; what it seals a prediction on is any
volume spike, anywhere, which is a different and much weaker claim. The
brief's own example — posted in X and Y, and Z wallets buy — is a conjunction,
and the company could not state one.

## Decision

### The agent chooses what the mechanism fires on

The discovery form gains `FIRES_ON: trigger | conjunction`. On `trigger`
nothing changes. On `conjunction` the mechanism records the second kind and
the window, and a prediction seals only when an event of the second kind
follows the trigger inside the window on the same instrument — at the
instant of the second event, which is the first moment anyone could have
acted, against the spot close at that instant. A second event that completes
several pairs is one occurrence: the conjunction happened once. The training
occurrence is the second event of the strongest instrument's first pair.

### The evidence shows both

For each horizon the material shows the effect after the trigger, the effect
after the conjunction completes, and the effect after any bar, on the same
recordings. An agent can see whether the follow-through is in the pair or
already in the trigger before it chooses.

### Old seals stay valid

The conjunction fields enter a mechanism's seal only when set. Every
mechanism sealed before this milestone hashes exactly as it did, and a test
recomputes the pre-M38 digest and compares.

## Consequences

- **A conjunction mechanism fires less often and claims more.** Fewer
  predictions per day, each one a test of the pattern the agent actually
  reasoned about. On the live workspace `MEC-0002` fires on ninety-one
  volume spikes in a day across thirty instruments; a conjunction mechanism
  would fire on the ones a second spike followed.

- **The mined pair is now expressible end to end**: mined, shown with its
  effect, stated as the thing that fires, predicted forward, scored against
  the drift. The brief's example needs the social and wallet event sources;
  the shape of the claim exists.

- **Not done.** Three-event conjunctions, and conjunctions across entities
  (an asset's funding and its spot instrument's break), stay unbuilt; each
  is the same rule with a wider join.
