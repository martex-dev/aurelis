# ADR-0031 — A mechanism is the join from a conjunction to a tested scheme

Status: accepted · 2026-09-11

## Context

M29 gave the company an event stream and the ability to mine it: a volume
spike followed by a range break on the same instrument within a day, thirty-
seven times on BTC-USD. M25 gave it a forward-scored judgement. The brief is
explicit that neither, alone, is a discovery, and states the critical design
point exactly:

> A mined pattern is not a discovery. It becomes one only when an agent can
> state a mechanism — why this would work, who is on the other side, what
> constraint or asymmetry makes it persist — and that mechanism must generate
> additional predictions beyond the one it was found on. Test those separately.
> Statistics alone cannot do it when the events are rare and the hypothesis
> space is effectively unbounded. Requiring a mechanism, and then testing what
> else the mechanism implies, can.

## Decision

### An agent states a mechanism, or the conjunction stays a conjunction

The discovery seat shows an agent a mined co-occurrence — the counts, per
instrument — and asks for a mechanism: a direction and horizon for the move,
a confidence, and three sentences a mechanism must have (why it works, who is
on the other side, how it decays). The prose is figure-checked. The count of
co-occurrences is in the material but is not a reason: a mechanism whose only
justification is "it happened often" is data mining with a sentence attached,
so the seat requires a *causal* reason and a decay model, and if the agent
cannot give one it says `nothing` and the conjunction stays a conjunction.

The mechanism is hashed and immutable (`mechanism/invariants.py`): one that
could be edited after its predictions came in is one fitted to its own
results.

### The mechanism predicts every future occurrence, scored forward

A mechanism implies a rule: when the trigger fires, the instrument moves this
way over this horizon. `generate_predictions` applies it to every occurrence
of the trigger whose horizon is still ahead of now, sealing each as a thesis
before its outcome exists, tagged with the mechanism, keyed by the trigger
event so one occurrence seals one prediction. Scoring flows through exactly
the M25 resolver. The reference close is what was knowable at the trigger; an
occurrence whose horizon already elapsed is the training data, not a
prediction, and is not sealed.

### The out-of-sample record decides, and the training instance is excluded

A mechanism's calibration is read from its tagged theses, excluding the
occurrence it was found on. A mechanism whose out-of-sample predictions beat
a coin toss *and* the base rate is a candidate scheme; one that gathers enough
scored predictions and does not beat the base rate is retired by the sweep,
with the reason, and kept — a mechanism that failed is the record that the
company does not fool itself. Mechanism firings carry their proposer as the
agent, but they are not that agent judging, so they are excluded from the
forward calibration the mandate reads.

## Consequences

- **Two real models declined.** Shown the spike-then-break co-occurrence on
  the live workspace — the one that fired thirty-seven times on BTC-USD — a
  Strategy agent and a Quant agent, on Sonnet, both **declined to state a
  mechanism.** That is not a failure. It is the design working: the seat did
  not let a pattern become a scheme because it occurred often, and the model,
  asked for a causal reason and who is on the other side, would not fabricate
  one. Requiring a mechanism separated a coincidence from a scheme, which is
  the entire point.

- **The full loop is exercised offline.** A deterministic stand-in states a
  deliberately-unfounded "forced-flow continuation" mechanism that always
  predicts up; its predictions seal, score against recordings as the clock
  advances, fail to beat the base rate of a market that only rises, and the
  sweep retires it. State, predict, score, retire — end to end, at no cost.

- **A parallel abandoned draft was removed.** An untracked `aurelis/schemes/`
  package, an incomplete second attempt at this same feature referencing
  enum values that never existed, was deleted. It was not wired into the
  schema, runtime or CLI and broke the type check. The tracked implementation
  is `aurelis/mechanism/`.

- **What this milestone did not do.** The mechanism reads only price-derived
  triggers, because those are the only events the stream holds; the memecoin
  example the brief names needs social and on-chain sources that are not
  built. No agent yet mines the stream to *choose* which co-occurrence to
  bring to the seat — an operator or the service names the trigger pair. And
  a mechanism that becomes a scheme is not yet turned into a strategy version
  or sized; it accrues a record, and that is where this stops.
