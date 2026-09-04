# Disclaimer

Aurelis is **research software**. It is not financial advice, and it is not a
product for managing money.

## No live trading

Aurelis has **no live-execution adapter**. `LiveBroker` is not written, not
registered, and not reachable. `Portfolio.mode` has no `LIVE` member. This is
an architectural decision, not a configuration flag — see
[ADR-0006](docs/adr/0006-live-execution-is-absent-not-disabled.md).

Backtest, simulation and paper trading are the only execution modes that exist.

## No claim of profitability

Nothing in this repository is proven profitable with real capital. The system
is deliberately built so that it can conclude that a hypothesis failed, that a
strategy has no edge, and that an apparent result was an artefact of the test.
Those outcomes are preserved with the same prominence as positive ones.

A backtest is not evidence of future returns. Neither is a paper-trading
record.

## What the integrity machinery does and does not promise

The event ledger is **tamper-evident, not tamper-proof**. Anyone with write
access to the database can alter it; they cannot do so without
`aurelis ledger verify` detecting it at a named sequence number.

Preregistration, append-only triggers and the risk-approval chain are enforced
by database constraints, which means they hold against raw SQL. They do not
protect against a modified copy of this software.

## Use at your own risk

Provided under the MIT License, with no warranty of any kind. If you connect
any part of this to anything that holds money, that is entirely your decision
and your responsibility.
