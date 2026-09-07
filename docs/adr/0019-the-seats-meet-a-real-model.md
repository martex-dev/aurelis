# ADR-0019 — The seats meet a real model

Status: accepted · 2026-09-07

## Context

M17 routed the charter's tier to a real model. The subscription was then signed
in, and for the first time something other than a scripted stand-in sat in one
of this company's seats.

Every seat was designed against that stand-in. The stand-in always answered in
`ANSWER:` / `BECAUSE:` form, always picked from the option set, and always cited
only figures it had been shown — because it was written to. Nothing in the
design had ever been contradicted.

The first five samples from a real model in the authoring seat produced **zero
usable answers**.

## What actually happened

```
0: ABSTAINED   "fixture data rather than live market data ... too short"
1: UNSOURCED   cited 91   (three months, derived from 2190 hourly bars)
2: ABSTAINED   "neither the sample nor the live data to support a claim"
3: ABSTAINED   "2190 bars ... about 3 months ... there is neither the ..."
4: UNSOURCED   cited 0.25 (2190 out of 8760, derived)

outcomes: {'abstained': 3, 'unsourced': 2}
```

Neither failure was the model behaving badly, and that is the whole finding.

**It abstained because our own honesty told it to.** The material says,
truthfully, `data: fixture, not live market data` and `bars available: 2190`. A
careful model reads that and declines to claim an edge. That instinct is right
and it was pointed at the wrong question — the seat does not ask for a claim, it
asks which design the company should test next, and the answer is preregistered,
measured, and usually refuted.

**It derived because the instruction invited it.** The prompt said "citing only
figures shown above", which a careful reader takes as *reason only from these*.
So it wrote `0.40%` for the 40 bps it was shown, and `0.25` for 2190 out of
8760. Those are derivations from shown figures, not confabulations — and the
guard refused them all the same.

## Decision

**Say what was meant. Do not widen a single guard.**

- `FIGURE_RULE` states the rule precisely — every number must appear *exactly as
  written*, no unit conversion, no ratios, no bars-into-months — and is appended
  to every closed question and every prose interpretation, so the guard and the
  instruction are the same sentence.
- The authoring system prompt says what the seat is: choosing a design is **not
  a claim that it works**, the data may be short or synthetic and that is a fact
  about the experiment rather than a reason to decline, and `nothing` is for
  when no option could be tested at all.
- `platform/llm/rehearsal.py` makes conformance a **number**: sample a seat's
  question *n* times, classify each answer by the exact path a real turn takes,
  and report usable / abstained / unsourced / unparseable.
- The seats use the configured provider; the stand-in answers only for `mock`.
- The caveat on every report is now computed from who actually answered.

After the change, both seats: **5/5 usable.**

## Rationale

### Why not widen the figure guard

Accepting derived arithmetic was the obvious alternative and it was rejected.
"Derivable from what was shown" has no floor — every number is derivable from
some others — and the guard would have stopped meaning anything. The guard was
never wrong; the instruction beside it was incomplete. A guard that rejects
behaviour the instructions invited is not enforcing sourcing, it is punishing a
reasonable reading.

### Why telling the model what the seat is, is not coaxing it

The worry is real: rewriting a prompt until the model stops refusing is how you
talk a system into agreeing with you. What makes this different is that every
sentence added is **true**. The design *is* preregistered. It *is* measured
against criteria fixed beforehand. It *is* frequently refuted — M15 and M16 both
end in the company reporting it found nothing. The model was declining because
it had been told half of what its answer was for.

The test of it is that no guard moved. `nothing` is still offered on every
question, the option set is still closed, the figure check still refuses, and a
turn that cannot be read still alleges nothing.

### Why conformance has to be measured

A guard that silently rejects most of what a model says is worse than no guard:
the seat looks occupied and produces nothing, and the only symptom is a command
that fails. Before `rehearse` existed, the symptom of a 0/5 seat was a traceback
forty frames deep. Conformance is now a number anyone can take at any time, and
it deliberately measures only whether an answer is *usable* — whether it is
*right* is what the scenario suite and the selection correction are for.

## Consequences

- **A real model authored a strategy end to end, and picked the best design in
  the space.** Reasoning only from the cost and the bar count, with no access to
  any result, it chose momentum / three-day lookback / half-percent threshold /
  long-only — which measures 0.0274, the highest Sharpe of all 72 designs, and
  beat buy-and-hold at 0.233 against 0.152.

  **That was one sample.** A later campaign from the same model chose the
  rotation branch and every one of its four attempts was negative. The
  selection correction is unmoved either way: 0.0274 against an expected best of
  0.0516 for a search that wide.

- **The report printed a falsehood the moment it became one.** Every M15/M16
  report ended "the designer behind this seat is a deterministic stand-in, not a
  model" — and kept saying it while a real model answered. `caveat_for` now
  resolves from the provider and the outcome carries what was true when it ran.

- **A real model reverted onto a design already measured.** Told its revision
  had done worse, it went back — correctly, and straight onto a design the
  campaign had already paid a declared cell for. A revision only knew its
  immediate predecessor. It is now shown the campaign's whole history, and an
  exact repeat is refused: re-testing a known number costs a cell and returns
  nothing.

- **Both seats answer identically every time.** 5/5 usable, and 5/5 the same
  choice. Conforming, and it has not decided anything the software could not
  have. The rehearsal says so in those words rather than reporting a clean
  score.

- **Running out of subscription allowance is an operating state.** It arrived
  as a traceback; it now reads as a sentence that says when the limit resets and
  that recorded work is unaffected.

- What is *not* done: no seat has been scored against **measured truth** with a
  real model in it. The M10 suite would do exactly that — twelve worlds, planted
  defects, the same marking — and it is the obvious next thing to point at a
  model. Until then, "usable" is all that is established.
