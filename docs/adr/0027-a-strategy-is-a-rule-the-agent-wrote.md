# ADR-0027 — A strategy is a rule the agent wrote, and the menu is gone

Status: accepted · 2026-09-10

## Context

ADR-0016 defined a strategy as five multiple-choice answers: a family, a
lookback, a threshold, and a direction or a breadth. Seventy-two reachable
designs, enumerated in advance, with the trading logic itself a hand-written
`if/elif` in the engine that the agent never touched. The brief for this stage
of the project says why that could never do what the project exists to do: an
agent cannot express an idea the grid does not contain, so it can never
produce something only it would use, and making the grid bigger does not help.
Combinatorial is not creative. The instruction was to delete it and not replace
it with a bigger menu.

ADR-0016 also had a reason for the menu that has to be answered rather than
discarded: authoring is cheap, and an agent that could author anything until
something passed would be a parameter miner with a rationale field. The menu
made the search countable, and the count was what the preregistration charged.

## Decision

### The agent writes the rule, in a language the engine runs

`aurelis.rules` is a small, closed, deterministic language: clauses read top
to bottom, each a condition over features of the closes up to the current bar,
each deciding `long`, `short` or `flat`. Eight features, windows up to 720
bars, at most eight clauses. It parses to a canonical structure that hashes the
same however it was typed, it cannot index forward, and a test changes the
future and asserts the past does not move. The engine gained one signal kind,
`rule`, which rebuilds the program from the registration's own payload so that
what runs is provably what was locked.

The agent is shown the desk, its costs, the budget in bars, prior work, and
the language reference — never a measurement — and replies with the rule, a
rationale and a weakness in one call. The rule's own numbers are the agent's
to choose; the rationale may cite them and the material and nothing else. A
rule that does not parse seals nothing. A second, closed question asks where
the rule came from, as before.

`authoring/design.py` is deleted. A test asserts the module does not exist.

### One rule is one declared cell, and that is a floor

There is no enumerable space behind a written rule, and pretending to count one
would be a number with no measurement behind it. Each rule the company measures
is one declared cell; a campaign's width is the number of rules it lets itself
write, declared before the first exists and frozen by the same trigger as
before. Whatever alternatives a model weighed inside its own reasoning before
writing a rule down are uncounted, and the docstrings say so in those words.
The forward record built at M25 is the check on that, not the denominator.

### The correction now demands a margin, because removing the menu exposed it

M16's `survives` was `surplus > 0`: the best result must exceed the expected
best of a search that wide. Under the null the best of *n* draws lands above
its own expectation about half the time, so that was a mean correction dressed
as a test. It went unnoticed while the declared width was 96 and the expected
maximum swamped everything. The first four-rule campaign on a **fixture**
survived it. A surplus must now clear the estimator's own standard error at
the one-sided 95% level as well. The four-rule fixture campaign no longer
survives; nothing that was not noise has been lost.

### The engine's own signals stay

`momentum`, `mean_reversion` and `rotation` are not deleted. They were the
menu's contents, but they are also the engine's registered operations that the
company's own review and training machinery plant defects into — the M5
survivorship review and the M10 scenario suite run on `rotation`. What is gone
is their availability to an agent as a choice. The agent writes a rule; the
engine runs it beside the operations it uses to test the company.

## Rationale

The rule language is deliberately a *mechanical-rule* language and not a
scheme language. It expresses what the existing preregistration, selection
correction, replication and gate machinery can honestly evaluate, and nothing
it cannot. Schemes over events and entities are the world model the brief
describes, and they need a different evidence regime; they are not built here.

## Consequences

- **A real model wrote a rule on 28,000 recorded BTC hours and lost 93% of
  the sleeve.** Sonnet wrote a two-clause rule around `sma(720)` and
  `sma(168)` that traded 1,339 times, paid 0.93 of the equity in costs, and
  returned −0.93 against +1.52 for holding the asset. Its own stated weakness
  was whipsaw in a range-bound regime, which is what happened. The company
  reported it as the headline. That is the seat working: the agent could
  write something the menu could not, and the measurement said what it was.

- **Every attempt recorded before M26 is a menu pick.** Their rows stand; the
  paper driver refuses to trade them with the reason that the menu no longer
  exists. The live workspace holds six of them.

- **The rehearsal command learned to rehearse a free-form seat.** The author
  seat no longer answers in `ANSWER:` form, so `rehearse` accepts a reply form
  and a reader, and classifies through the seat's own parser.

- **The stand-in's policy is narrower than a model's.** It writes one of two
  rules and revises along one path. That is what makes the offline campaign
  deterministic, and it is also why the offline campaign's result says
  nothing about what a model would write.

- **Not done:** no filter, sizing or exit component beyond the position the
  rule states; one instrument per rule; no cross-sectional rules; no critic
  reads a rule before it is measured.
