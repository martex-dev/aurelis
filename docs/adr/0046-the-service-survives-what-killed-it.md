# ADR-0046 — The service survives what killed it, and a token fill is honest

Status: accepted · 2026-09-24

## Context

On 15 September at 18:46 UTC the first wake to follow memecoin tokens ran
its agent loop, sealed its predictions, and reached the scheme step. The
range-break mechanism, a candidate scheme since the previous wake, fired on
a token priced at $0.00058782 and tried to open a $5,000 paper position.

Four things then went wrong in a row:

1. Every price on an order was stored rounded to eight decimal places. The
   order's quantity had been sized to the exact price; the stored price was
   rounded up; the database's check that an order may not exceed its
   approval compared the rounded product in floating point and refused.
2. The refusal happened inside the wake's shared database session. The
   scheme step caught the exception but the session was already poisoned,
   and the commit at the end of the step raised again.
3. That second exception left the wake. Nothing in the service loop caught
   a failed wake, so it left the loop too.
4. The process exited. No stop was recorded, and the machine restarted for
   a Windows update the next morning. Nothing was recorded for nine days.

The position itself was also wrong. A $5,000 order against a pool holding
$64,745 claims to have moved through 8% of the pool at the quoted price.

## Decision

### Prices are exact

A new column type, `Price`, stores eighteen decimal places. It is used for
every price on orders, fills, positions and post-trade reports. Amounts of
money keep eight places. Bar prices were already stored as exact text.

### The order-size rule tolerates float noise, and is replaced when it changes

The SQLite trigger now allows one part in a billion over the approval. That
is binary floating-point noise, not an excess anyone could trade on. It is
dropped and recreated on every initialise, so a workspace created under the
old rule gets the new one. Postgres compares in exact NUMERIC and is unchanged.

### A failure is contained where it happens

Each paper order runs inside a savepoint: opening a firing, closing a trade,
flattening a residual. A failed order is rolled back alone, and the firing is
refused with the rule's own words in the note. Each mechanism's trading runs
inside a savepoint of its own in the wake. A wake that raises anyway is a
critical incident, with the traceback printed in the service window, and the
next wake runs on schedule. Three failed wakes in a row stop the service with
the reason recorded, because a failure that repeats every hour needs a person.

### A token position is capped by its pool

A position in a token keyed by chain and contract is capped at 2% of the pool
liquidity its newest attention event reported. A position under $100 after
the cap is refused with the pool size in the note. A token with no liquidity
on record is refused.

### The service restarts itself

`scripts/run-aurelis.ps1` starts the station if it is not running and runs
the service in a loop, restarting it a minute after it exits for any reason.
It loads source keys from `<workspace>/keys.ps1` when that file exists.
`scripts/install-autostart.ps1` registers a Windows scheduled task that runs
the supervisor at logon. It changes a setting on the operator's machine, so
the operator runs it; Aurelis does not.

## Consequences

- Replaying the failed step on a copy of the live database opened all 18
  firings with none refused. The token with the $64,745 pool got a $1,294.90
  position instead of $5,000.
- Orders stored before this change keep their eight-place prices. They are
  historical and are not rewritten.
- **Not done.** Nothing checks that the machine stays awake. Sleep suspends
  the service without killing it, and it resumes on wake with its schedule
  intact, but nothing is recorded while the machine sleeps. The liquidity cap
  uses the newest reported liquidity, not the depth at the moment of the fill.
