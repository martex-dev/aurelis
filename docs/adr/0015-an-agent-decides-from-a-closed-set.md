# ADR-0015 — An agent decides from a closed set, and is scored on the decision

Status: accepted · 2026-09-07

## Context

M13 finished the roadmap. Two things stand between what exists and the
objectives this project was started for — *creating* a profitable strategy, and
earning with it — and one of them is that **agents do not yet reason**.

M10 built the instrument for measuring judgement: twelve worlds with planted
defects, truth established by replication, and a marking scheme that grades
against measurement rather than against the author's intent. What it scored was
a `Playbook` — a set of numeric thresholds. Its own docstring said what was
missing:

> What the harness proves today is that the company can measure a procedure and
> refuse to ship a worse one; what it will measure when agents reason for
> themselves is the same thing, through the same harness, with the agent in
> place of the thresholds.

`interpret_as` already asked models for prose and refused any figure the model
had not been shown. Prose is the wrong shape for this: a critique that cannot
be compared against a planted defect cannot be scored, and a critic scored on
nothing is a critic nobody can improve.

## Decision

**An agent answers a `Question` with a closed option set, and the answer is
parsed, not interpreted.**

- A `Question` carries its `Choice`es. The options are rendered into the
  prompt, and an answer naming anything else raises `UndecidableAnswer` — not
  a warning, not a fuzzy match. A near-miss matched loosely would be the parser
  deciding rather than the agent.
- `NOTHING` is always offered and always legitimate. A decision surface with no
  abstention produces a critic that finds something every time, which is the
  exact failure the null scenarios exist to catch.
- The justification is held to the **same figure rule as prose**: every numeral
  must appear in the material shown. An agent that reasons to a conclusion
  using a number nobody gave it has not reasoned.
- A turn that cannot be read alleges **nothing**, and the marking counts every
  real defect on that scenario as missed. A critique nobody could act on is not
  a critique, and scoring it as neutral would make an unreadable critic look
  average.

An `AgentCritic` is then interface-compatible with a `Playbook` where the suite
needs it, so it runs through `TrainingSuite` over the same bench, the same
draw, and the same marking.

## Rationale

The demonstration is the argument, and it did not go the way a headline would
want.

```
playbook       caught 7/8, false alarms 1/31
agent          caught 8/8, false alarms 8/31
the gate       REFUSED
```

The agent caught **everything the suite plants**, including the defect the
shipped procedure misses. It also raised objections against eight
specifications that did not have one. The regression gate M10 built compares on
counts and refuses a revision that raises more false alarms, so it refused this
one — and it refused on arithmetic, not on taste.

That is the result worth having. **Finding more is not the same as being
better**, and a company that promoted the critic with the higher catch rate
would have promoted the one that makes reviews unreadable. The gate is also not
a rejection stamp: restricted to survivorship alone, where the same agent
catches all three planted cases and raises nothing spurious, it ships.

## Consequences

- **What sits behind the seat in this repository is not a model.** Every model
  call here runs against the mock provider, and a mock that echoes its input
  cannot answer a multiple-choice question — so a deterministic stand-in
  supplies the answers. What is exercised is the machinery: the closed option
  set, the parse, the figure check, the refusal path, the scoring, the gate.
  Point the runtime at a real provider and the same code path asks a real
  model. Every report of a seating says this in those words, and a test asserts
  the caveat is present.
- The stand-in is deliberately given a **different policy** from the incumbent —
  readier to allege, on a lower bar. One tuned to agree would produce an
  identity and teach nothing.
- A comparison restricts **both** sides to the same specialty. One side facing
  more questions than the other would report arithmetic rather than evidence.
- Building the stand-in caught a bug of exactly the kind this whole layer
  exists to catch. Its regex for the headline metric was anchored to the line
  after the section heading — but `render_material` sorts a section's keys, so
  the caveat line sorts above the measurement. It matched nothing, `had_a_result`
  was false on every scenario, **every stress defect was suppressed
  everywhere**, and the stand-in scored 4/8 and read like a considered
  difference of judgement rather than a broken regex.
- Strategy synthesis is the obvious next seat: the same surface, with authored
  components as the closed set. It is not built here.
