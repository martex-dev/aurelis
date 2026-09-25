# ADR-0054 — A changed catalogue is a new question

Status: accepted · 2026-09-25

## Context

M50 and M51 added Reddit's feed, Telegram channels, X and Discord to the
source catalogue. Three live wakes then ran, sealed nineteen views and made
thirty-two paper fills, and no agent was asked about the new sources. Only
Bluesky and Stocktwits were read.

The agenda puts an action only while the mandate condition it serves is
unmet. Choosing sources serves `sourced`, which had been met for days. The
exhaustion rule's own message said "a new source in the catalogue is a new
question", but the chooser never reached it.

The seat also told the agent that the company "reads only free, official
sources". That was no longer true after the operator's decision in ADR-0051,
and an agent taking it literally could decline the new sources on principle.

## Decision

- **Standing duties.** An agenda action may be *standing*. It runs whenever
  it has work, even after its condition is met, and before the other actions,
  because each is one cheap question that has work only when something
  changed. Choosing sources is the first standing duty: whenever a
  market-intelligence agent has not answered on the current catalogue, it is
  asked.
- **The seat describes the catalogue truthfully.** The sources are free and
  approved by the operator. Some are official APIs, and some are read,
  read-only, through the operator's machine and accounts. A source that needs
  a sign-in is read once a person has signed in.

## Consequences

- Any future catalogue change reaches the agents at the next wake, at the
  cost of one call per market-intelligence agent.
- Actions that are not standing still wait for their condition. The mandate
  still decides what the company works toward.
