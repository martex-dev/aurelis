# ADR-0028 — The service wakes under a grant, and records what broke

Status: accepted · 2026-09-10

## Context

M25 made the company's evidence forward: a view is sealed before the outcome
and scored when a recording covers the horizon. That record grows only if
something records the market after the horizon and seats the judges again,
and until now that something was a person typing `aurelis data fetch` and
`aurelis thesis resolve`. ADR-0025 was explicit that the autonomy loop does
not fetch, because fetching is the one action that reaches outside the
company and an unattended loop is the last place that should happen without a
person.

The brief asks for a company that runs for days and weeks, waking on
schedules, and that keeps working when APIs go down, data arrives malformed or
a model is out of allowance — and records what broke. Both requirements meet
at the same question: who decided the company may fetch?

## Decision

### A person grants, once, on the record

`aurelis service grant` records a `DataGrant`: vendor, desk, instruments, bars
per fetch, who granted it, when, and why in a sentence. The row is frozen by
three triggers — nothing but the revocation may change, a revocation is
written once, and a grant is never deleted. The service fetches nothing that
is not on an active grant. A grant is a decision a person made; the loop still
cannot make it, and nothing under `aurelis/service/` calls `grant`, which a
test asserts by reading the source.

### A wake is four steps and none of them stops the next

Fetch under the grants. Settle every view a recording now covers. Run the
autonomy loop inside what is left of a rolling daily model-call budget. Write
one row per wake, whatever happened. A vendor that is down is a warning alert
raised by the Operations Director — the charter whose remit is system health
and which holds the alert scope; the service is not an agent and cannot write
an alert in its own name, and the write-scope guard refused it on the first
run, correctly. A provider out of allowance is recorded by the loop as a failed
action, and the wake row says the run happened and what it cost. The next wake
retries.

### The daily budget is read from the service's own record

Model calls are counted from the service's wake rows, on the runtime's clock,
not from the provider's call records, which are stamped by the wall clock. The
difference is the difference between a budget that resets and one that never
does under a frozen clock — and between a budget the tests can prove and one
they cannot.

### It still does not trade

No live adapter exists and this package adds none. A static test parses every
module under `aurelis/service/` and asserts nothing imports trading or a
broker.

## Consequences

- **The company can run unattended for a day or a week.** `aurelis service
  start --every 1h --for 7d` wakes hourly, fetches the granted instruments,
  settles what is due, seats the judges on the fresh recordings, and stops
  when the duration is up or the operator interrupts — with the reason on the
  ledger either way.

- **The forward record accumulates on its own.** In the test, four wakes a
  day apart score every 24-hour view and seat the judges again each time; the
  calibration report reads more scored views after each wake.

- **Incidents are alerts, on the station.** The service page shows the
  grants, the last wakes with what each fetched, scored and spent, and every
  incident with whether it is still open. The header's alert count includes
  them.

- **Not done:** the service wakes on a clock only. Waking on a market event
  or on another agent's finding is the next thing the brief asks for and is
  not built. Nothing resolves a thesis against anything but a close.
