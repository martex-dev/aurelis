# ADR-0006 — Live execution is absent, not disabled

Status: proposed · 2026-09-04
Strengthens: `CLAUDE.md` §13

## Context

`CLAUDE.md` §13 requires a `BrokerAdapter` abstraction with `PaperBroker`,
`BacktestBroker` and a `LiveBroker` "disabled by default."

martex-quant already holds a stronger line, and states it in its own README:

> "Live execution is not reachable from this CLI, is never a dashboard button,
> requires your own broker credentials and a deliberate command-line action,
> and sits behind a risk guard whose KILLED latch only a human can clear. Those
> gates are deliberate. Please leave them there."

Its `live/guard.py` `KILLED` latch "is never cleared by code; removing it is a
deliberate human act after understanding what died."

## Decision

**No `LiveBroker` implementation exists in the Aurelis repository.** The
protocol is defined; the adapter is not written, not registered, and not
reachable.

Additionally:

- `Portfolio.mode` has no `LIVE` member. Adding one is a schema migration and a
  review, not a config change.
- No Aurelis module imports `martex_quant.live.mt5_broker`, and a test asserts
  it.
- Aurelis creates no new path to martex-quant's existing live machinery. Its
  gates stay exactly as they are.
- Enabling real-money trading is a separate, separately-scoped, separately-
  reviewed project.

## Rationale

"Disabled by default" is one flag from enabled, and flags get flipped by
accident, by a config merge, by an agent that found a settings file, or by a
tired human at 2am. **An absent adapter cannot be enabled by a flag.** The
distance between paper and live should be a code review, not a boolean.

This is deliberately stronger than what `CLAUDE.md` asks for. If it proves too
strong, it is one ADR to reverse — which is exactly the friction that should
exist in front of this particular change.

## Consequences

- The system is architecturally complete without ever being able to lose money.
- The `BrokerAdapter` protocol is still designed now, so adding a live adapter
  later is an implementation rather than a redesign.
- Paper trading remains the terminal deployment state for the foreseeable
  future — which, given 174 trials, one surviving strategy, and that strategy
  killed by its own correction, is where the evidence says it belongs.
