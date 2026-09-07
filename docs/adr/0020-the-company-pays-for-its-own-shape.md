# ADR-0020 — The company pays for its own shape

Status: accepted · 2026-09-07

## Context

Every one of the 76 charters has declared a `ModelTier` since M1. Until M17 the
field cost nothing and meant nothing: every call site passed the same string, so
the declaration had nothing downstream of it.

Routing changed that. An agent routes at the **highest** tier of the charters it
covers, because it must be capable of its most demanding role. The consequence
is arithmetic: a generalist holding one expensive charter runs *all* its work on
the expensive model, including the cheap charters it also holds.

At the launch roster that is **25 charters** — AUDIT alone spans low, mid and
high, so five of its six run five times dearer than they were written for.

M11 already had everything needed to act on this: declared triggers,
preregistered predictions, applied changes, measured effects. What it did not
have was a metric for it. Its own docstring says adding one "is how the company
becomes able to make a new kind of prediction about itself."

## Decision

**`overtiered_charters` is a metric, `TIER_WASTE` is a trigger, and the company
reorganises itself on the reading.**

- `overtiered_charters` counts the charters an agent holds whose declared tier
  is strictly below the tier it routes at. Exactly derivable from coverage and
  the charter registry, so it is checkable rather than trusted.
- `ModelTier.NONE` is **excluded**. That tier means the work calls no model at
  all, so holding it costs nothing however the agent routes.
- The `TIER_WASTE` trigger fires at **three**, proposes `FISSION`, and the
  subject is *scanned for* rather than named.
- The prediction is on the **subject's** count, where fission acts directly,
  and it is hashed before the Board is convened.
- `model_tokens` is added alongside as an observational metric.

## Rationale

### Why the prediction is about the subject, not the company

Moving everything below the top tier off an agent leaves the *new* agent holding
a spread of its own — and routing at the highest of *that*. So the company total
improves by less than what moved. Predicting the company total would be a claim
about the new agent's composition, which this change does not control; the
subject's count going to zero is the tight, falsifiable claim that fission
actually makes.

The company total is reported beside it anyway, because it is the number that
matters and a report showing only the subject's would be claiming a fix it did
not make.

### Why the saving is not printed in dollars

Every model call in this repository reports zero marginal cost, because the
company is running on a subscription. **No money saved has been observed and
none is claimed.** What is measured exactly is the structure: how many charters
run above the tier they were written for, before and after. The rate table is
quoted — `high` input is 15 per Mtok against 3 at `mid`, five to one — as what
the gap is worth on the metered path, and labelled as such.

This is the same discipline as everywhere else: report what was measured, cite
what is known, and do not let a plausible inference wear the clothes of an
observation.

### Why the threshold is three

Two is a pair, and a company that reorganised over a pair would never stop.
Three is declared in the trigger table with every other threshold, before any
reading is taken — a threshold chosen after the reading is a justification.

## Consequences

- **The company reorganised itself six times, on its own evidence, and stopped
  when its own rule said to.**

  ```
  1. AUDIT   moved 5   company 25 -> 21
  2. RISK    moved 4             21 -> 17
  3. INTEL   moved 3             17 -> 14
  4. TRADE   moved 3             14 -> 11
  5. KNOW    moved 3             11 ->  8
  6. INFRA   moved 3              8 ->  5

  agents 17 -> 23,  trigger no longer fires
  ```

  It does **not** reach zero. Five charters remain overtiered, held by agents
  below the threshold of three — CIO by one, STRAT by two, and the new agents'
  own spreads. That is the declared rule working, not an oversight, and the
  report says which.

- **The first split predicted −5 and got −5, while the company improved by 4.**
  The subject went to zero exactly as locked; the new agent routes at `mid` and
  holds a `low` charter, so one of the five it received is still above its
  written tier. Both numbers are on the report.

- **Every guarantee held under a new kind of change.** Coverage moved and was
  never dropped, the proposer was not the subject, the prediction was hashed
  before the room convened, and the new agent ran the scenario suite before it
  was allowed to work.

- **This is the company improving itself on evidence it gathered itself** —
  M17's routing produced the measurement, M11's lifecycle acted on it, and
  neither milestone was built with the other in mind. That is the argument for
  having built the organisation first.

- What is *not* done: the improvement is structural, and no agent has yet been
  shown to *research better* after a reorganisation. The scenario suite could
  measure that — score an agent, split it, score it again — and it has not been
  pointed at a real model yet.
