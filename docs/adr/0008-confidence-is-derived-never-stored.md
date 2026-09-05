# ADR-0008 — Confidence is derived, never stored

Status: accepted · 2026-09-05
Implements: `CLAUDE.md` §1.5, §15
Supersedes: the `MemoryEntry.confidence` / `confidence_cap` columns sketched in
`docs/04-domain-model.md` §8

## Context

`CLAUDE.md` §1.5 forbids the company from saying a strategy is profitable
unless the evaluation criteria justify it, and asks for precise states rather
than confident adjectives. §15 asks for institutional memory that preserves
failed hypotheses, replication failures and reasons for rejection.

The domain model's first sketch gave memory entries a stored `confidence` and a
`confidence_cap`. That is the obvious design, and it is how most research
knowledge bases do it.

It has one fatal property: **a stored confidence is only correct until
something changes, and nothing makes it change.**

The M6 acceptance criterion is "a finding's confidence degrades when an
objection opens against it." With a column, satisfying that means every code
path that files an objection must remember to recompute every affected
finding — as must every path that resolves one, records a replication, adds a
correlation edge, or overturns a verdict. Each of those is a place the update
can be forgotten, and the consequence of forgetting is not a crash. It is a
number that reads as current and is not. The one time it matters is the time
nobody remembered.

## Decision

**There is no confidence column.** `memory/confidence.py` computes a band on
read, from the record, every time it is asked.

- The band is ordinal — `NONE < WEAK < MODERATE < STRONG` — and never a number.
  "0.72 confidence" reads as a probability, is not one, and starts being
  averaged and thresholded across findings that were never commensurable.
- Rules are **caps, not contributions**. Evidence raises the band; anything
  wrong with the finding lowers it; the lowest cap wins.
- An objection that is merely **open** lowers the band. It need not be upheld
  or even tested. Resolving it in either direction lifts the cap.
- Only the *explanation* is persisted, on `Finding.confidence_cap_reason`, so a
  reader of the raw table sees the reasoning without re-running the module.
- The knowledge graph assigns no confidence of its own. It records
  relationships with citations; weighing them happens here.

## Rationale

**Derivation makes the acceptance criterion structural rather than
procedural.** An objection filed at three in the morning by a path nobody
anticipated lowers the band the next time anyone asks, with no coordination and
no hook. The property holds because there is nowhere for it to fail.

**Caps beat contributions because the failure they prevent is the expensive
one.** A scoring scheme that adds up supporting evidence can, given enough
supporters, outweigh an unresolved critical objection. That is precisely how a
research organisation talks itself into a bad position — not by ignoring the
objection, but by burying it under agreement. Making every defect a ceiling
means the objection cannot be outvoted, only answered.

**A band refuses to say more than it knows.** MODERATE and STRONG are
distinguishable and defensible. 0.71 and 0.68 are not, and the moment they
exist somebody will sort by them.

**Only one of the two can go stale.** A cap *reason* that lags is a cosmetic
problem a reader can spot. A cap *value* that lags is indistinguishable from a
correct one. So the reason is stored and the value is not.

## Consequences

- Assessing confidence costs four queries per finding. At M6 volumes this is
  irrelevant; if it ever is not, the answer is a materialised view that can be
  rebuilt from the record, not a column that cannot.
- Reports must call `assess()` rather than reading a field. The vault export
  does, per page, at export time.
- `docs/04-domain-model.md` §8 no longer lists a `MemoryEntry` with a
  confidence column. The entity is gone; what it was for is computed.
- There is no way to override a finding's confidence by hand. Raising it
  requires changing the record — more independent support, a replication that
  held, an objection answered — which is the only honest route anyway.

## Alternatives considered

**Store it and recompute on write.** Rejected: correctness then depends on
every writer remembering, and the failure is silent. This is the design the
decision exists to avoid.

**Store it with a `stale` flag.** Rejected: it moves the problem to who sets
the flag, and a reader who ignores it is back where they started.

**A numeric score.** Rejected: it implies a calibration nobody performed. If
the company ever earns a calibrated probability, it will come from scored
forecasts (`meetings/forecasts.py`, Brier), which measure something real —
not from arithmetic over edge counts.
