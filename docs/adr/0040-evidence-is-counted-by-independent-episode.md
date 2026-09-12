# ADR-0040 — Evidence is counted by independent episode

Status: accepted · 2026-09-12

## Context

At 05:05Z on the 12th the first wake after a restart scored a backlog and
`MEC-0001` became a candidate scheme: 26 out-of-sample predictions, 25
right, Brier 0.1162 against the drift's 0.2700. It opened two paper
positions through Risk. Every one of those twenty-six predictions came from
about eighteen hours of the 11th, across thirty instruments that move
together. A range break on ADA at 14:00 and one on DOT at 14:00, both
followed by a rise over six hours, are one fact about 14:00 on that day.
The library counted them as two, and twenty-six such facts as twenty-six.

M31's bar — twenty scored predictions, better than a coin toss and better
than the instrument's own drift — was written when one instrument fired a
few times a day. Thirty instruments turned it into a bar one good afternoon
could clear.

## Decision

### Predictions whose horizons overlap are one episode

Sorted by reference bar, across every instrument, a prediction joins the
current episode if its reference bar is inside the horizon of the episode's
first prediction, and otherwise starts the next. Thirty instruments in the
same hour are one episode. The same mechanism firing on Monday, Wednesday
and Friday is three.

### Enough means enough episodes too

A mechanism's record is read as evidence only with at least twenty scored
predictions **and** at least ten episodes. Below either it is gathering, and
the verdict says which: `gathering (36/20 predictions, 3/10 episodes)`.

### It must beat the drift by episode as well as by prediction

Each episode's Brier is the mean over its predictions, and the mechanism's
episode Brier is the mean over episodes — an afternoon with thirty
predictions weighs the same as a morning with one. The base-rate forecaster
is scored the same way. A scheme beats the drift on both readings; a
mechanism that wins thirty times in one hour and loses the other nine hours
has not beaten the drift. Retirement uses the same test and its reason
prints both readings.

### A position always closes at its horizon

Paper positions were opened and closed inside one function called only for
candidate schemes. A mechanism demoted while holding positions would have
held them forever. Closing is now its own step, run every wake for any
mechanism with open trades, scheme or not, at the resolution close of the
prediction that opened it.

## Consequences

- **`MEC-0001` is gathering again.** Twenty-eight predictions over a handful
  of episodes is a handful of observations; the page says
  `gathering (26/20 predictions, N/10 episodes)`, its two open positions
  close at their horizons, and no new one opens until the episodes are
  there. That is the right reading of one good afternoon.

- **The station and the CLI count episodes** beside predictions, with a
  second bar of `episodes / 10`.

- **The scripted fixtures still work.** The M31 edge fixture spikes every
  thirty bars with a six-bar horizon, so each spike is its own episode and
  the scheme tests hold; the M30 retirement fixture breaks every five bars
  and merges pairs of overlapping horizons, and still retires.

- **Not done.** Episodes are cut by time alone. Two instruments that do not
  move together in the same hour are still counted as one; a mechanism on
  an uncorrelated universe is under-counted, which errs toward caution. A
  correlation-aware cut is the refinement.
