# ADR-0004 — Market desks are the second organizational dimension

Status: accepted · 2026-09-04

## Context

Aurelis covers crypto, equities, options, futures, commodities, FX and
memecoins. Those markets differ in instruments, calendars, data, cost models,
liquidity, and in what a valid experiment even looks like — testing an options
volatility signal is not testing a crypto momentum signal.

Three ways to model that: one universal engine (wrong — it would have to be the
intersection of every market's capabilities), duplicated departments per market
(wrong — nine departments × seven markets is unmanageable), or a second
dimension.

## Decision

**A Desk is an orthogonal axis crossing every department. An agent is
`(role, desk)`.**

```
Desk:
    desk_id · instruments[] · calendar · trading_hours
    data_sources[] · engines[] · cost_model · liquidity_model
    risk_limits · constraints
    status  PROPOSED | OPENING | ACTIVE | DORMANT | CLOSED
```

A Technical Analyst on the Options desk and one on the FX desk share a charter
and differ in tools, data, playbooks and cost models. Opening a desk is
registering a `DeskConfig` and staffing it — **no architectural change**.

Engines are adapters behind a common protocol, and each declares its
`capabilities()`. An agent asking the crypto engine for greeks gets a typed
refusal rather than a wrong number.

## Rationale

- **Desk × role is what takes the company to hundreds of agents naturally.**
  Seven desks × 76 charters is the ceiling, approached only where evidence
  justifies each hire.
- Research is comparable across desks because it goes through the same ledger,
  the same registration discipline and the same gates — with per-desk
  thresholds registered as configuration.
- Cross-desk transfer becomes a first-class activity: a Brainstorm on options
  volatility can deliberately seat the crypto analyst and the macro analyst,
  and the knowledge graph records the `INSPIRED_BY` edge.
- The existing small tools map cleanly onto desks: `vol-surface` and
  `implied-move` to OPTIONS, `roll-yield` to FUTURES and COMMODITIES,
  `factor-exposure` to EQUITIES, martex-quant's `meme/` to MEMECOINS.

## Consequences

- Every research record carries a `desk`, and cross-desk claims must say which
  desks they were tested on. `GENERALISATION_OVERREACH` is an objection type
  precisely for claims that leak across desks without evidence.
- Desks open in stages, cheapest first: CRYPTO (the engine and lake exist),
  then EQUITIES, OPTIONS, FUTURES, COMMODITIES, FX, MEMECOINS.
- A desk with no research for a declared window goes `DORMANT`, and closing one
  requires a recorded reason. Dormant desks cost nothing.
- Per-desk cost, liquidity and risk models are mandatory configuration. A desk
  without a realistic cost model cannot be opened, because a backtest without
  one is not evidence.
