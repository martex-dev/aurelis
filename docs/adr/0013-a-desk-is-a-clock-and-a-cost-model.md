# ADR-0013 — A desk is a clock and a cost model, and research must be converted between them

Status: accepted · 2026-09-07

## Context

M12 opens the six desks that were declared and dormant. The roadmap's
acceptance criterion has two halves, and only the first is obvious: "each desk
runs a complete mission end to end **and its research is comparable across
desks in the ledger**."

The second half did not work, and the reason was in plain sight. The engine
reported Sharpe with `unit="per_bar"`. That was honest — and useless. A per-bar
Sharpe of 0.05 on hourly crypto bars is an annualised 4.7; the same 0.05 on
hourly NYSE bars is an annualised 2.0, because a year of crypto has 8760 hours
in it and a year of the NYSE has 1638. An archive that ranked the two side by
side would be ranking them by **sampling frequency**, and would conclude
reliably that the fastest-sampled desk did the best research.

Nothing in the system stopped that. Cross-desk comparison was not wrong; it was
absent, and the absence looked like a small formatting detail.

## Decision

**A desk carries a calendar, and every cross-desk figure is converted through
it.**

1. `TradingCalendar` declares `periods_per_year` per interval, **per
   calendar** — 8760 hourly bars for 24/7, 1638 for XNYS, 5796 for CME, 6240
   for 24/5. Declared, not derived: the derivation is where the error lives,
   and 252 sessions of 6½ hours is 1638, not 8760 and not 6132.
2. An interval a calendar has not declared raises. A guessed conversion factor
   silently rescales every Sharpe on the desk.
3. Metrics are classified `RATE`, `DRIFT`, `LEVEL` or `COUNT`. Rates are
   multiplied by `sqrt(periods per year)`; levels are not touched; **counts are
   refused**, because a trade count on an hourly desk and one on a daily desk
   are different questions rather than one question at two scales.
4. A metric with no declared scaling is **refused**, never passed through. An
   unconverted rate looks exactly like a converted one.
5. Two measurements taken over very different windows are refused outright.
   Annualisation fixes the frequency mismatch and does nothing about a quarter
   compared against a decade — which is the more dangerous error, because the
   conversion makes it look rigorous.

**And a desk carries its own cost model**, per asset class, split into
per-trade, per-holding-period, per-contract and impact. A round trip costs
40bps on crypto and 760 on memecoins; carry is charged on *time held* so a slow
strategy cannot escape funding; per-contract fees stay in dollars because on a
cheap option a fixed fee exceeds the spread.

## Rationale

The conversion factors differ by 2.31× between the widest pair of desks. That
is not a rounding difference; it is larger than the gap between most of the
seven results the demonstration produced.

But the sharper consequence only appeared once claims were stated properly. A
claim is worth stating **annualised** — "a Sharpe of 1" means the same thing to
everyone. Converting an annualised claim down to a desk's per-bar minimum
effect divides by `sqrt(periods per year)`, so a high-frequency desk chases a
smaller per-bar effect and needs more bars. The two cancel exactly:

> **The same annualised claim needs the same number of years on every desk, and
> a completely different number of bars.** Settling an annualised Sharpe of 1
> takes about 3.84 years everywhere — 33,655 hourly bars on crypto and 6,295 on
> equities.

From which: **a research budget stated in bars is not a budget.** Handing every
desk "1,200 bars" gives crypto seven weeks and equities nine months, and
systematically underpowers whichever desk samples fastest while looking
scrupulously even-handed. The company now states research budgets in years.

## Consequences

- Every desk has a calendar, and a desk whose calendar is undeclared **cannot
  be opened**: without it, nothing that desk produces is comparable with
  anything.
- `RunArtifact.diagnostics` carries the calendar and the periods-per-year, so a
  result can be annualised long after the run. A result that lost its clock
  cannot be converted afterwards.
- Two bugs fell out of building the fixtures, and both were silent. **Tick size
  is a desk property**: at a cent tick an FX rate of 1.00 never moved and a
  memecoin priced at four thousandths of a cent quantized to zero, so two of
  the seven desks produced perfectly flat series — and the engine ran, the
  metrics computed and the verdict rule returned `UNDERPOWERED` without
  anything reporting that the input had been a constant. "Prices move" is now a
  readiness check, and a desk that fails it does not open.
- `Readiness` has three states, not two. Every desk M12 opens runs on fixture
  data with no live feed, which is `PROVISIONAL` — never a pass, carried on the
  opening record, and repeated on the desk's own page. A desk cannot quietly
  graduate from "open on fixtures" to "open" without somebody writing down what
  changed.
- The options desk is open and the local engine still cannot compute a single
  greek. That is a typed refusal rather than a zero: the desk can be researched
  as a price series and not as an options book, and the test that used to
  assert "the engine refuses the options desk" now asserts the refusal that is
  still true.
