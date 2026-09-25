# ADR-0049 — The company evolves how its agents think

Status: accepted · 2026-09-25

## Context

The operator asked for a company that "evolves itself and works on its own".
After M47 the company worked while there was work. But it did not change how
it worked in response to what the record said about its work.

The record said something plain. The agents' own forward views scored a Brier
of 0.263 against 0.25 for a coin toss: worse than chance. The one mechanism
that cleared the bar, MEC-0001, was stated by an agent. But the same agents
kept forming views the same way. Nothing in the system could change *how* an
agent reasons, only which agents were seated and on what.

A role's prompt is fixed in code, and changing it by hand for every agent is
the anti-pattern the brief names: "hard-coded agent prompts everywhere". It
also puts the person, not the company, in charge of what the company learns.

## Decision

- **Every judging agent may carry a written method**: a short text, at most
  900 characters, saying how it forms a view. It is versioned per agent,
  append-only, and has a ref (`MTH-`). The method is part of the agent's
  identity at every seat: judging, discovery, the critic and the sources
  seat. Every prompt the agent receives says which version it is working
  under.
- **A method's fitness is its forward record.** It is the mean Brier of the
  views the agent sealed *since the method was adopted*, with a standard
  error. With fewer than 20 scored views the method is `unproven`. It is
  `failing` if it is worse than a coin toss by more than one error,
  `thriving` if better by more than one error, and at `chance` otherwise.
- **Once a day the company measures every method.** A failing agent gets a
  new method. The best-calibrated thriving colleague writes it, shown the
  failing agent's worst calls and the colleague's own fitness. If no
  colleague is thriving, the failing agent revises its own method from its
  worst calls. It is one high-tier call per failing agent. The new method
  records the fitness it has to beat, and its window starts at zero.
- **A reply that is not in the `METHOD:` / `BECAUSE:` form adopts nothing.**
  The run says which agents it could not give a method to.
- **The wake runs evolution** after the schemes and before the brain sync, at
  most once in 24 hours, and only while the day's budget has calls left. A
  failure is an incident from `service.evolution`, not the end of the wake.
- The brain shows each analyst's method version and fitness. The Obsidian
  Agents page shows the method text. `aurelis evolution status` and
  `aurelis evolution run` expose it to the operator.

### The figure guard read names as numbers

While measuring the judges, the record showed that most of what looked like
abstention was refusal. On the latest recordings six of seven judges were
refused at the market stage for "citing figures not shown": `-0001`, `-0006`,
`0.203`, `0.237`. The first two are the ends of `MEC-0001` and `AG-0006`,
which the numeral pattern read as negative numbers. The others were the
shared brain's own Brier scores. The brain sits in the system prompt, and
the market stage only counted the material block as shown. M46 had therefore
made every judge that cited the brain unable to answer.

- **A digit run glued to a word is part of a name**, not a figure. The
  pattern ignores digits preceded by a letter, a digit, an underscore, a dot,
  or a hyphen that follows a word. `-3%` after a space is still a figure, and
  it is still checked.
- **Everything an agent was shown counts as shown.** That includes the system
  prompt (the brain, notes and method) and the rendered prompt, at the market
  stage, the view stage, discovery and the critic. A figure that appears
  nowhere in the prompt is still refused.

### One vendor, one pace

The first M47 wake was refused by GeckoTerminal (429) on tokens it had read
an hour earlier. The token follower and the trending-pools source each paced
themselves, so together they ran at twice the vendor's free limit. A
process-wide pacer (`intel/pacing.py`) now gives each vendor one interval,
whichever reader is asking. A 429 is waited out for as long as its
`Retry-After` asks, capped at 90 seconds, and the token reader tries three
times before it records the token as unread for the hour.

## Consequences

- The company can now change how an agent reasons without a person editing a
  prompt. It does so only on forward evidence, and only where the evidence
  says the current way is worse than guessing.
- A method's window restarts at adoption. A new method cannot inherit the
  old one's views, good or bad, so it takes 20 new scored views before it
  can be judged. At the current seating rate that is about a day.
- The evolution is itself on the record. Every method records who wrote it,
  why, and the baseline it was written against. Whether rewriting methods
  improves calibration is therefore a question the record can answer. If it
  does not, the record will show that too.
- **Not done.** Methods are not yet tested against each other on the same
  views, so a method is compared with its own predecessor rather than with an
  alternative. The mechanism-discovery seat carries the method but its
  fitness is not yet measured by the mechanisms the agent states.
