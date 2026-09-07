# ADR-0016 — Authoring is a search, and the search is declared

Status: accepted · 2026-09-07

## Context

The project exists to **create** a profitable strategy rather than to find one.
M8 built the surface for it — `author_component` and `compose`, with a required
rationale and a citable origin — and refused, deliberately, to provide any
function that promotes a hypothesis into a strategy. What it did not have was
an agent. Until M15 the pieces were written by hand in a test fixture, which
means the claim "agents write pieces" was true of the software and not of the
company.

M14 seated an agent as a critic, judging a specification somebody else wrote.
This is the other seat, and it is the one the project was started for.

The danger is specific and it is not "the agent might design something bad".
Authoring from a menu is *cheap*: seventy-two designs, each a few seconds of
engine time. A company that lets an agent author until something passes has
built a parameter miner with a rationale field attached, and the rationale
makes it worse — it makes the mining legible as reasoning.

## Decision

**An agent picks a whole strategy from a closed, enumerable space, and the
preregistration declares the size of the space rather than the size of the
pick.**

- Five slots (`family`, `lookback`, `threshold`, and then `direction` or
  `breadth` depending on the branch) give **72 reachable designs**, enumerated
  by walking the branch structure. The branches have different widths, so a
  product of slot sizes would be wrong — and wrong in the direction that
  overstates the search.
- `declared_cells = 72`, not 1. `trial_count` already sums declared cells per
  family, so a second attempt costs the denominator a second 72.
- Costs, universe and warm-up are **not slots**. They come from the desk.
- The origin question is asked but is **not part of the space**, because it
  changes no number.
- The agent chooses before anything has been run on the data it will be scored
  on, so the lock is a lock rather than a description of a decision already
  made.
- Every justification is figure-checked against the material and the options,
  and a design that cannot be read whole is refused with nothing written.

## Rationale

### Why the space and not the pick

Only one backtest runs, so charging for seventy-two looks like
over-punishment. It is not. The agent was shown the alternatives and reasoned
over them, and **nothing in the record can establish which ones it implicitly
weighed.** Faced with a quantity that cannot be measured, a false-discovery
denominator has exactly one defensible direction: the conservative one.
Understating it manufactures confidence out of arithmetic, and the whole reason
`declared_cells` exists is that the company decided a grid should pay for its
own width whether or not every cell was run.

The origin question is the boundary case that shows the rule is a rule and not
a reflex. It is a real decision with real consequences — it is the field the
novelty count is computed from — and it is not charged, because it cannot move
a result. Charging for it would inflate the denominator as dishonestly as an
inert knob would deflate it.

### Why every slot had to be swept before it was written down

A knob that is hashed into a specification, charged to the denominator, and
justified in an agent's own words, but which cannot change any number, is
decoration. Decoration in a preregistration is worse than absence: it makes the
search look wider than it was, and it produces reasoning about nothing.

This was not hypothetical. Sweeping the candidate space design by design, every
rotation design returned an **identical Sharpe for all three thresholds**,
because the cross-sectional signal never read the parameter. The engine gained
the parameter rather than the space losing the slot — `_rotation` now takes a
floor a name must clear, defaulting to zero, which is what it always did — and
the sweep is now a test that fails if any choice in any slot stops mattering.

The same sweep is why `direction` is not offered on the rotation branch. That
signal cannot take a short, so the option would have been a knob with no hole
behind it.

### Why the agent cannot author its own costs

`COST_UNDERSTATED`, `SURVIVORSHIP` and `LOOKAHEAD` are three of the defects M10
scores the company's own critic on catching. An authoring surface that offered
those knobs would let an agent manufacture exactly the result that critic
exists to refuse, and the two halves of the company would be working against
each other by design. The desk sets them, identically for all 72 designs, and
a test asserts it over every one.

## Consequences

- **The result is negative, and it is the headline.** On the crypto fixture,
  over a quarter of hourly bars, the authored design returned 2.6% where
  holding the asset returned 24.3%, paying 9.2% in cost drag to do it. The
  verdict on the registered claim is UNDERPOWERED — settling an annualised
  Sharpe of 0.5 on this desk needs about 15 years of hourly bars, which is
  M12's finding again and is reported with the shortfall attached so nobody
  reads it as a defect in the design.
- **The baselines are references, not registered claims.** `always_long` and
  `never_trade` run after the fact, over the same window at the same costs.
  The comparison against them is labelled post-hoc everywhere it appears,
  because a post-hoc comparison presented as a test is the move preregistration
  exists to prevent. It is also the only part of the result that does not
  depend on power: the design lost to buy-and-hold by a margin no interval
  argues with.
- **The closed option set was not itself citable, and now is.** M14's figure
  check permitted only numerals from the material. M14's options were prose, so
  this never showed; M15's carry numbers — a lookback of 168 bars, a threshold
  of 0.02 — and an agent could not justify a pick by referring to the pick.
  `decide_as` now treats the rendered question as material. A guard that
  refuses an answer for citing the question is not checking sourcing, it is
  punishing specificity.
- **The stand-in's reasoning did not match its answer, and a demonstration
  caught it.** It justified every origin with "the company already paid for
  this answer once" while picking `invented` on a workspace with an empty
  graveyard. It passed the figure check — it cited no figures — and read as
  considered provenance. There is now one justification per origin.
- **What sits behind the seat is not a model**, and the data is a fixture. Both
  caveats are on every report, in those words, and a test asserts they are
  present.
- What is *not* built: the company does not yet author a second design in
  response to the first one failing. The machinery for it exists — `mutate`
  produces a new version rather than editing one — but a revision loop is
  exactly where authoring turns into mining, and it should not be added without
  deciding first what stops it.
