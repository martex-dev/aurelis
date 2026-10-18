# ADR-0066 — The strategy lab

Status: accepted · 2026-10-18

## Context

The operator wants the company to "go through literally every way to earn
money": ICT, SMC, indicators, moving averages, order blocks, every market,
every timeframe. Only after that should it develop its own methods. The
company had never done this. Its research had been:

- martex-quant's crypto corpus (imported at M6);
- a closed rule language over hourly crypto bars (M26);
- agents' judgement on a few weeks of hourly crypto.

No stock, forex, commodity or futures price had ever been recorded. The
taught strategies had never been tested side by side under one honest
standard.

## Decision

**A strategy lab (`aurelis/lab/`) tests every taught strategy, on every desk
with free data, with costs and a correction for luck.** It is software: no
model call. CLAUDE.md asks for exactly that for backtests.

- **History (`history.py`).** Daily bars for:
  - the granted crypto, from Coinbase's public candles;
  - 15 equities, ETFs and indices, 7 FX pairs, 6 commodities and 4 index and
    rate futures, from Yahoo Finance's public, keyless chart endpoint.

  Stooq was tried and now answers with a browser check. The lab does not try
  to get past checks meant to keep programs out. Every series is stored as
  an artifact, and the run names their digests.
- **Catalogue (`strategies.py`).** There are 18 settings, each run long-short
  and long-only:
  - SMA crossovers;
  - time-series momentum;
  - Donchian breakouts;
  - RSI(2) and RSI(14) reversion;
  - Bollinger reversion;
  - MACD;
  - mechanical approximations of the ICT fair value gap and the SMC
    liquidity sweep, named as approximations.

  A position at bar *t* uses bars up to *t* only. A test alters every later
  bar and checks that no earlier position moves.
- **Judgement (`evaluate.py`).** A strategy is judged in three steps:
  - **Costs.** Every change of position pays half the desk's documented
    round trip, and every day held pays the desk's carry.
  - **Luck.** Each series is split 70/30. In sample, the Sharpe must clear the
    best Sharpe expected from N strategies with no edge (Bailey and López de
    Prado), where N is every strategy times every market tested in the run.
  - **The unseen 30%.** Out of sample, the Sharpe must be positive and the
    strategy must beat holding the market.

  The verdicts are *survived*, *failed out of sample* and *no better than
  luck*.
- **Record.** `lab_runs` holds what was tested on and what failed to fetch.
  `lab_results` holds every strategy on every market, in sample and out, and
  is append-only.
- **What the company does with it.**
  - Every seat's briefing carries one *Lab* line. It gives the counts, the
    survivors, and each family's out-of-sample Sharpe averaged over **every**
    market, so it is not the cherry-picked best.
  - The Quant Research room's tab is the lab.
  - `aurelis lab run` and `aurelis lab show` run it and report it by hand.
  - The service reruns it weekly.

## Consequences

- The company now knows, on every desk with free data, which taught methods
  survive an honest test. The expected answer is very few or none. That is
  the floor the agents' own ideas have to clear, and the reason the company
  should not just pick a popular strategy.
- The luck bar is strict. Strategies across markets are correlated, so N
  overstates the independent tries. A survivor here is a genuine signal, and
  a near miss is not proof of no edge.
- The lab adds a few minutes of fetching to one wake a week.
- **Not done.** Daily bars only. Intraday versions of these strategies need
  intraday history, which only crypto has, from the service's own
  recordings.
- **Not done.** No walk-forward re-fitting and no portfolio of survivors.
  Each strategy and market is judged alone.
- **Not done.** Options, NFTs and memecoins are not in the lab. There is no
  free options history, no NFT feed, and the followed tokens have weeks of
  history, not years.
