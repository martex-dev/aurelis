# ADR-0026 — A judgement is sealed before the outcome exists, and scored when it does

Status: accepted · 2026-09-10

## Context

Everything the company has measured about an agent so far is a measurement of
a *rule the agent chose*. M15 put an agent in the author's seat; what it chose
was one of 72 designs somebody had written down in advance, and what was
scored was the design. That is a menu, and a menu cannot contain an idea only
the agent would have had. The brief for this stage of the project says so
plainly and says the menu has to go.

Replacing it runs into the hardest constraint in the whole design. **An
agent's judgement cannot be backtested.** A model asked what it thinks about
BTC in March 2020 already knows what happened; every historical decision it
makes is contaminated by hindsight it cannot switch off, and the number that
comes out is worthless and convincing. Any design that replays history and lets
the agents trade it is measuring memory rather than skill.

So the evidence has to be forward, and the platform already has the two
mechanisms that make forward evidence enforceable rather than promised: a
hash-chained ledger, and Brier scoring over probabilities recorded before an
outcome (built at M3 for meeting forecasts, and barely used since).

## Decision

### The agent chooses; the option set is what the company can check

The seat asks two questions. *Which market?* — every instrument the company
holds a recording of, with a software-computed summary of each and the agent's
own record so far. *What do you think, and how sure are you?* — a horizon from
a closed set, a direction, a confidence, a thesis in the agent's own words, and
what would make it wrong.

The instruments on offer are not a menu of ideas. They are the boundary of
what is scorable: a view on an instrument nobody recorded has no reference
close to seal against and no bar to settle it with. Widening the boundary is a
matter of recording more, which `aurelis data fetch` does for any product the
vendor serves.

The horizons are closed for the same reason. A horizon is a resolution
mechanic: the resolver has to know which bar settles the proposition, and a
horizon that fell between bars would be settled by whichever bar somebody
picked.

### The prose is figure-checked; the confidence is the one number invented

The thesis and the falsifier are held to the figure rule every other seat is
held to: every numeral must appear in the material. The confidence is parsed
out of its own line and is exempt, because inventing it is the job.

### Sealed means the database refuses

A thesis records the reference close it was made against, the instant it
resolves, and a SHA-256 over every field that matters. Three triggers hold it:
nothing sealed may change; the resolution columns may be written only while
`scored_at` is null; nothing is deleted. A prediction whose confidence could be
nudged after the outcome is a prediction that can be made to look calibrated,
and calibration is the whole measure.

### Forward means `resolves_at > sealed_at`, and the seat refuses otherwise

The one way a "forward" prediction quietly becomes a backward one is a stale
recording. If the last bar the agent was shown plus the horizon it chose lies
before the clock, the outcome already exists in the world, and the seat seals
nothing. It is also a `CHECK` constraint on the row.

### Scored once, mechanically, strictly above

When the horizon has passed and a recording *extends past it*, the close of the
bar that opened at the horizon settles the proposition. A close equal to the
reference is not above it. No recording covering the horizon means pending,
never a guess.

### Calibration is the measure, and it is cut three ways

Mean Brier against the coin toss (0.25). Hit rate against stated confidence,
by band, so over-confidence shows as a gap. And the Brier of always predicting
the observed up-frequency, so a record that has learned the drift of the market
and nothing else does not read as skill.

### The mandate gains an eleventh condition, and the loop gains an action

`calibrated`: at least thirty scored views on market recordings with a mean
Brier below the coin toss. Second in the standard, after `live_data`, because
it is the only condition about the agents' own judgement and the only one that
cannot be produced by searching harder. The standard's digest moves; the
assessment history shows the move.

The autonomy loop's `judge` action settles what a recording can settle and
seats one agent. It is exhausted when every judging agent holds an open view on
every recorded market: a second view on the same instrument before the first
resolves is the same bet placed twice. Its stop reason says the honest thing —
what is missing is time and a fresh recording, and the loop fetches nothing.

## Rationale

Five hundred views sealed in advance and well calibrated is not something that
can be overfit into existence, and it is exactly what a sceptic cannot wave
away. It is slower than backtesting and it is the only honest version. It is
also faster than it sounds for the class of idea this company should be
hunting: a 24-hour view produces a scored row in a day, and a company seating
seven agents on three markets accumulates a record at the speed of the market
rather than the speed of a search.

## Consequences

- **Real agents sealed real views.** Seven agents on Sonnet, three fresh
  Coinbase recordings, fourteen model calls: six views sealed, one abstention,
  zero refusals — every reply was in the required form on the first try, which
  no other seat in this repository managed on its first contact with a model.

- **Six views, one opinion.** Every sealed view says *down*. Five are on
  BTC-USD at 0.55–0.60, one on ETH-USD at 0.56. Seven agents with different
  charters read the same twenty-four closes and drew the same conclusion in
  slightly different words. That is not a society disagreeing; it is one view
  written six times, and the record will score it as six. The identity in the
  system prompt makes the agents distinguishable; it does not make them
  independent. Independence needs different evidence, which needs the event and
  entity layer the brief describes, and an adversary whose job is to attack a
  view before it is sealed. Neither is built here.

- **Half the falsifiers restate the proposition.** "Wrong if the close at the
  horizon is above the reference" is the resolution rule, not a falsifier.
  Nothing checks this yet, and it should: a falsifier that adds no information
  is the agent declining to say what it would take to change its mind.

- **Nothing is scored.** The first five views resolve on 2026-09-11 at 19:00Z
  and the sixth on 2026-09-13. Until then the forward record is empty and the
  station says so.

- **The response cache handed one agent another agent's answer.** Two agents
  shown identical material, same system prompt, produced one model call: the
  cache key ignores who asked, correctly, for identical questions. The seat now
  carries the agent's handle, department and charters in the system prompt. A
  society whose members are the same prompt with different names is one agent.

- **The seal did not survive a round-trip.** A confidence written as `0.65`
  reads back as `0.65000000`, the eight-place scale the Money type stores, and
  `verify_seal` failed on every row it read. The seal is now computed over the
  stored form on both sides.

- **Refusals were rolled back with the transaction that refused.** A judgement
  that fails raises out of its session, taking the event that recorded the
  refusal with it. The refusal is now appended in a transaction that commits,
  because an agent that keeps producing unreadable views is a fact about the
  agent.

- **The stand-in declined everything on the crypto fixture** on the first
  offline run, because its regex for a market key did not allow the slash in
  `btc/usdt`. Found by running the command, as every bug in this project has
  been.

- **A fixture recording anchored in January would expire every horizon.** The
  fixture feed lays its bars against the clock so that offline runs can seal
  anything at all; the row says it is a fixture, the seat tells the agent so,
  and the mandate does not count it.

- **The design space is still there.** `authoring/design.py` and the 72-point
  menu back four of the mandate's conditions and the paper driver, and removing
  them is its own milestone rather than a side effect of this one. The brief's
  instruction stands and is not yet carried out.
