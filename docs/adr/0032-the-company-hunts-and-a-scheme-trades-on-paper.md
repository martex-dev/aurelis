# ADR-0032 — The company hunts for mechanisms on its own, and a scheme trades on paper

Status: accepted · 2026-09-11

## Context

M30 built the join from a mined conjunction to a tested scheme, and left three
gaps that stood between it and "agents developing their own strategies". An
operator named the pattern to bring to the seat, so the company did not hunt.
The trigger vocabulary was two price events, so a real model had little it
could say a causal story about — and two of them, correctly, said nothing. And
a mechanism that earned a calibrated record never became a position, so the
record ended in a table rather than in a book.

Building the third gap found a flaw in the second milestone's own bar.

## Decision

### The base rate a mechanism must beat is the instrument's unconditional drift

M30 measured a mechanism against the up-frequency *among its own predictions*.
That frequency is conditioned on the trigger — it is the signal — so a
mechanism right on every firing had a base-rate Brier of zero and could never
beat it. A perfect mechanism read as worse than the base rate. The base rate
is now the fraction of bars in the newest recording whose close ``h`` bars
later was above their own: what a forecaster who knew only the drift would
have said, scored against what happened. A test builds a market whose drift is
a coin toss and whose post-spike six hours always rise, and the mechanism is
a scheme.

### The company hunts

`mine_pairs` ranks every ordered pair of event kinds that co-occurs on the
same instrument inside a window. The autonomy loop's `discover` action brings
one (agent, pair) to the discovery seat per cycle, one active mechanism per
trigger kind, and is exhausted when every mined pair has been put to every
judging agent on the events that stand — the same last-word rule the
judgement seat uses, because the same material gets the same cached answer.
It runs after `judge`, so the forward record of views is never starved by
the hunt. The mandate has a twelfth condition, `scheme`, that the action
targets.

### Four more derived events

Momentum flips, volatility squeezes and expansions, and drawdowns, each
recorded once per entry into the state and each a function of the bars up to
its own. Still price-derived; still the only events the stream holds.

### A candidate scheme trades on paper, through the same chain as anything else

Only a candidate scheme trades. When it does, nothing is special-cased. The
mechanism is composed into a strategy version through the synthesis surface —
by the Strategy Architect, because the write-scope guard refused the
researcher who stated it, which is the org design working — with the
mechanism's own why as the rationale, its decay model as the known weakness,
and the composing task as the invented origin. It is given five percent of
the paper book, and every firing becomes an intent through `PaperCycle`:
Risk, approval, execution, post-trade. A position opens at the reference close
of the firing and closes at the resolution close when the prediction scores,
so the mechanism's paper P&L is the realised sum of round trips it was right
and wrong on, after fees. A firing whose horizon already passed unopened is
never opened: a round trip on it would be hindsight.

P&L is reported and never judged. Over a short window it is mostly luck; the
mandate does not read it; the calibration record is the measure and the
paper book is where a calibrated mechanism shows what that is worth after
costs.

## Consequences

- **On the live workspace the first view scored.** STRAT's six-hour ETH short,
  weakened by the critic to 0.52, was right: Brier 0.2304 over one. Twenty
  more stand.

- **The whole loop is now unattended.** A service wake fetches, syncs the
  catalogue, derives events, settles views, seats judges, brings mined pairs to
  agents, seals every active mechanism's forward predictions, retires the ones
  that fail, and trades the ones that earned it — under a grant a person
  recorded, inside a daily model-call budget, with every failure an incident.

- **Not done.** The triggers are all price-derived, so the memecoin example
  still cannot be expressed; a scheme's share of the book is a constant, not
  a function of its record; nothing closes a paper position early on a kill
  latch; and the paper book's positions are not yet on the station beside the
  mechanism that made them.
