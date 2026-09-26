# ADR-0060 — The station shows the path to real money

Status: accepted · 2026-09-26

## Context

The operator's question is whether the company is ready to earn money. The
company's own answer has existed since M21: a standard of conditions, each
read from the record, that must all be met before it asks a person to trade
real money. The assessment runs on every cycle of the autonomy loop. The
station showed none of it. The brief asks that a person understand the
company through Mission Control without a terminal, and the most important
thing to understand was reachable only through `aurelis mandate assess`.

## Decision

A `/mandate` page, linked as **money** in the station's navigation, shows:

- **The latest assessment.** It shows the verdict, how many conditions are
  met, and for each condition whether it is met, what it asks, and what the
  record says.
- **Every scheme's paper record after costs** (ADR-0056): round trips,
  independent episodes, won and lost, P&L after fees, drawdown, and verdict.
- **The last twenty assessments**, so a condition that was met and then lost
  is visible.
- **A plain statement** that no live adapter exists, and that until every
  condition holds, the honest answer to "is it making money?" is the scheme
  table.

The page reads the stored assessment rather than computing a new one. What
the operator sees is what the company recorded, at the time it recorded it.

## Consequences

- The operator can see how far the company is from asking to trade real
  money, and why, without opening a terminal.
- **Not done.** The page does not yet show the trend of each condition's
  reading over time, only the verdict history.
