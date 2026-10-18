# ADR-0068 — The company thinks faster, and uses what the allowance allows

Status: accepted · 2026-10-18

## Context

The operator asked how much the subscription can give the company, and for
it to run "24/7… developing fast… whatever usage, calls, time". The service
was set to 1,200 model calls a day and 100 a wake, but it never got near
that. WAKE-0561 spent its 100 calls between 01:55 and 05:22, three and a
half hours for one hourly wake: about 30 calls an hour, about 700 a day at
best.

The model was not the slow part:

- **Calls.** On the live record, a Sonnet call took 27 seconds on average and
  an Opus call 18. Consecutive calls were about 90 seconds apart.
- **The shared brain.** Profiled on a copy of the live database, one view
  seat with the free stand-in took 19 seconds, 15 of them in the shared
  brain's record. Its cache was keyed on a fingerprint that changes whenever
  any view or mechanism prediction is graded, which on the live company is
  nearly every minute. A rebuild read every mechanism's base rate through
  482,000 bar rows built as ORM objects.
- **The mandate.** The readiness check runs on every cycle of the loop, and
  it re-verified the whole hash chain: 26 seconds for 528,000 events, several
  times per action.

There was a second constraint. The subscription's allowance is shared with
everything else the operator runs, and it is not published as a number. On
18 October it ran out at 00:55Z, the alarm from ADR-0061 fired, and the
service simply retried at full speed afterwards.

## Decision

1. **The brain's record is reused for five minutes** (`BRIEF_TTL`), whatever
   has been graded since. After that, the fingerprint cache works as before.
   A summary five minutes old is the same summary. Tests set the TTL to zero
   so they read the record as it is.
2. **Bars are read as plain rows**, not ORM objects (`Snapshots.bars_of`),
   which removes most of a cold rebuild's cost.
3. **The mandate's chain check is incremental within a process.**
   - A full pass runs at most hourly. In between, `Ledger.verify_since`
     checks only the new events, the first linked to the last chain hash
     this process proved.
   - That checkpoint lives only in this process's memory and is never written
     down, so the record never trusts a checkpoint written by the code it
     checks.
   - A broken link, a forged hash or a missing event still fails, and the
     next check after a failure is a full pass. Tests cover all three.
   - The daily audit duty still verifies the whole chain.
4. **The wake budget adapts to the allowance** (`adaptive_wake_budget`):
   - the allowance ran out in the last six hours: half the operator's
     per-wake budget;
   - it ran out earlier in the last day: three quarters;
   - it has held for a day: the full budget.

   It never goes above what the operator set. The wake's note says when the
   budget was cut, and why.

## Consequences

- The overhead between calls falls from about a minute to seconds. That
  should take a wake of 100 calls from hours toward the hour it is meant to
  fit in, and the day toward the 1,200 the operator set. This is to be
  measured on the live record after the restart, not assumed.
- The company backs off on its own after running out, instead of hitting the
  wall again and again, and recovers by itself.
- **Not done.** Seats still run one at a time. SQLite has one writer, and a
  seat holds a write transaction across its model calls. Parallel seats need
  each seat's writes separated from its thinking, which is a larger change.
- **Not done.** The fast lane for meme coins (minute-level watching, with
  models woken only when something fires) is still to come.
