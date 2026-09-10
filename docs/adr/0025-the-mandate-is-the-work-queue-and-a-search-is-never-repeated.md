# ADR-0025 — The mandate is the work queue, and a search is never repeated

Status: accepted · 2026-09-10

## Context

`aurelis tick` has advanced the company's working day since M2: due jobs fire,
stranded work clears, every active agent gets a turn. What it cannot do is
decide what the day is *for*. Everything above that level has been an operator
typing a command — `strategy author`, then `strategy campaign`, then
`research replicate` — which means the company has never chosen its own work.

Building the layer that does turned out to be almost entirely about stopping.

## Decision

### The mandate is the work queue

The company already publishes a standard it must meet before asking to trade
real money, and `aurelis mandate assess` already reports which of the ten
conditions it misses. So the loop carries no plan. Each cycle it asks itself
what it is missing, takes the first action that could move one, and checks
whether it did.

A hard-coded sequence would be a plan somebody wrote, running unattended, and
the first time the company's state diverged from that plan it would keep
executing it anyway. Every `Action` names exactly **one** condition — an action
claiming several would keep looking useful after the one it actually served was
met.

### Repeating a search is not progress

This is the rule the whole layer exists for.

If a campaign ran and `survived_selection` is still unmet, running a second
campaign does not improve the odds of the first. It widens the declared search
space, which *raises* the surplus the best design has to clear — and it raises
it faster than searching finds anything. An unattended loop that kept searching
until something passed would not be a research company. It would be a machine
for manufacturing false discoveries, with the company's own preregistration
machinery producing the paperwork for each one.

So every action declares when it is **exhausted**, and returns a *reason*
rather than a boolean: "we already did this and it did not work" is the most
important sentence an autonomous loop can produce, and a boolean throws it
away.

### It stops, and says what it gave up on

When every action that could move something unmet has been taken, the loop
stops. `stuck_reasons` reports each remaining condition with why the company
cannot act on it. A loop that stopped silently would be indistinguishable from
one that crashed.

### Two things it is not allowed to do

**It does not fetch data.** Fetching is the one action in this company that
reaches outside it, and an unattended loop is the last place that should happen
without a person. There is no action whose condition is `live_data`.

**It does not trade.** Not disabled — absent, as it has been since ADR-0006.
The `paper` action exists and refuses on an empty book.

It also cannot lower a bar it failed to clear: the standard lives in
`mandate/standard.py`, it is hashed, and nothing in `aurelis/autonomy/` writes
to it.

## Consequences

- **The company ran itself.** On a subscription, against 28,000 recorded hours
  of BTC-USD: campaign, then a research review, then a replication, then it
  stopped — 18 model calls in under four minutes. The review is the part worth
  reading: the critic raised survivorship, the generated test came back
  `max_drawdown 0.124 -> 0.645` once three delisted names were restored, and a
  **confirmed claim was refuted**. Nobody intervened. `reviewed` moved to MET
  and the mandate went from 3 of 10 to 4.

- **Nothing else moved, and the loop said why.** Five conditions came back with
  a sentence each: the campaign has run and a second is not the answer; every
  replication found nothing to replicate; no version has cleared its gates, and
  deployment refuses on evidence rather than on anything a retry could change.
  That is the loop working, not failing.

- **The first run replicated five times and learned nothing five times.** Five
  different registrations across five cycles, each returning
  `NOTHING_TO_REPLICATE` because each original had been underpowered. By the
  letter that is not repetition — every registration was new. In effect it is
  exactly repetition, and the rule now reads the company's own record: if every
  replication so far found nothing to replicate, another one writes the same
  row again.

- **A failed action was retried forever.** The exhaustion rules read persistent
  state, and a *failure* usually leaves none — a refused authoring writes
  nothing at all, deliberately, so `_authored_already` kept counting zero and
  the loop re-ran it every cycle until the cycle bound stopped it. Six identical
  failures, recorded six times. An action that failed is now exhausted for the
  rest of the run. Found by the test suite, on the plain mock provider, which
  is exactly the state a workspace pointed at a provider that is down would be
  in.

- **Counting a table by name crashed the second cycle.** The rules counted
  `campaigns`; the table is `authoring_campaigns`. Nothing checked the string.
  The rules take mapped classes now, so the same mistake is an `ImportError` in
  the test suite rather than an `OperationalError` in an unattended run.

- **The review does not review the authored designs.** `hold_research_review`
  builds and attacks its own survivorship claim on fixture data. It raises real
  objections, settles them by measurement, and moves the condition honestly —
  but the mandate's `reviewed` criterion counts objections against *anything*,
  so a critic that has never read the company's actual strategies can satisfy
  it. That is a hole in the standard, it is recorded here, and it is not
  something the loop should paper over.
