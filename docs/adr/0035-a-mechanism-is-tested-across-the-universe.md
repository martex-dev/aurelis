# ADR-0035 — A mechanism is tested across the universe, not on one chart

Status: accepted · 2026-09-11

## Context

`MEC-0001` was stated on sixteen range breaks of one instrument and needs
twenty out-of-sample predictions before the company will call it anything.
The live grant named three instruments, so the mechanism could fire three
times a day at most and in practice about once. Weeks to a verdict, on a
claim about *range breaks*, not about bitcoin.

Prediction generation never cared which chart a mechanism was found on: it
seals one prediction per occurrence of the trigger kind, on whatever
instrument the event fired. The universe was the only throttle, and the
universe was a list a person typed.

## Decision

### A grant may be drawn from the venue's own liquidity ranking

Coinbase publishes, without credentials, every product's last day in one
document. `aurelis service grant --universe USD --top 30` reads it once, ranks
the USD-quoted instruments by **dollar notional** — volume times last, because
by units a memecoin with half a trillion of them outranks bitcoin — and grants
the top thirty. `aurelis service universe` shows the same ranking and writes
nothing.

### Pegged instruments are excluded by measurement, not by name

A stablecoin against the dollar sits third by notional and moves a tenth of a
percent all day; a range break on it is noise. The rule sets aside any
instrument whose 24-hour range was under 0.2%, and says so on the grant. A
list of stablecoin names would be stale the week it was written; the
measurement is not.

### The selection is a decision, made once; the rule is its provenance

The instruments that came out are what the service may fetch, exactly as if a
person had typed them. The rule and the ranking it was drawn from are on the
record — the grant names the rule in words and the ranking's artifact digest —
and both are frozen by the same trigger that freezes the instrument list. The
service does not re-run the rule. A grant that re-ranked itself every wake
would be the widening-after-the-fact the M27 invariant exists to refuse.

### An instrument on two grants is one instrument

The wake fetches and reads each instrument once per vendor and notes how many
were named twice. Two permissions for the same thing are not two things.

## Consequences

- **On the live ranking the day this shipped**, the top by notional were
  BTC, ETH, ZEC, USDT, XRP, SOL, HYPE, and by units the top were PEPE, MOG,
  BONK — none of which is in the notional top twenty. USDT was set aside as
  pegged. The grant on `live/` is thirty instruments where it was three.

- **A mechanism's evidence arrives at the universe's rate.** The test in this
  milestone states a mechanism on one instrument, records a second one, and
  the mechanism seals on the second's breaks, none marked as training, and
  scores on the second's own recording. On the live workspace `MEC-0001` now
  seals wherever a range break fires across thirty charts, and so does
  `MEC-0002` — *leveraged liquidation-cascade exhaustion reversal*, down over
  24h at 0.55 after a volume spike — which a Research agent stated during the
  first wake on M33 code while four others declined the spike-then-spike pair
  as volatility clustering with no side. Both are gathering; neither is a
  scheme.

- **The judge's first question lists thirty markets** where it listed three:
  one summary line each. Tolerable, and watched; if it crowds the prompt, the
  seat will offer a slice and say how it was cut.

- **Not done.** One venue, one quote asset. The rule is fixed at grant time on
  purpose, so a listing that becomes liquid next month is not fetched until a
  person grants again; the catalogue events say when that has happened.
