# ADR-0014 — A claim is a compare-and-set, and coverage is two-dimensional

Status: accepted · 2026-09-07

## Context

M13 is scale and hardening. Two things had to be true for it and neither was.

**The queue silently did work twice.** `TaskQueue.claim` selected the
highest-priority queued task and then wrote `CLAIMED` onto it, with a docstring
asserting that Postgres' `SKIP LOCKED` and SQLite's single-writer model each
made that safe. The first half is true. The second is not: SQLAlchemy opens a
DEFERRED transaction on SQLite, so the `SELECT` takes no lock at all. Two
workers read the same queued row, both wrote their own name onto it, and the
later commit won without complaint.

Eight workers against forty tasks produced **fifty-three claims and no error**.
Thirteen tasks done twice, each drawing its own budget, each producing its own
artifact. Nothing anywhere reported a problem — the counts only look wrong if
somebody counts them.

**Coverage had one dimension where it needed two.** ADR-0004 said desks are the
company's second organisational dimension and that an agent is
`(charter, desk)`. `Charter.desk_specific` existed and *nothing read it*.
Coverage was a flat set of charter ids, so there was one Technical Analyst for
the whole company — and M12 opening six desks gave that person six more markets
rather than giving six desks an analyst. The roadmap's "100+ agents across
seven desks" was not merely unreached; it was unreachable.

## Decision

**The claim is a compare-and-set.** The candidate is selected, then written
with a conditional update:

```sql
UPDATE tasks SET status='claimed', claimed_by=?, claimed_at=?
WHERE ref = ? AND status = 'queued'
```

The affected-row count decides. A worker that loses the race sees zero rows
updated and moves to the next candidate, up to a bounded number of attempts.
`SKIP LOCKED` stays on Postgres — but as an efficiency, not as the guarantee.

**Coverage is `(charter, desk)`.** `AgentCoverage` gains `desk` as part of its
primary key. Thirteen of the seventy-six charters are desk-specific and are
held once *per open desk*; the other sixty-three are held once for the company,
with `desk = ""`. Seven open desks means **154 slots**, and `aurelis.org.slots`
computes which the company owes, who holds them, and which nobody does.

## Rationale

The claim fix is correct on every dialect and does not depend on an isolation
level, which is the only kind of concurrency guarantee worth writing down. The
version it replaced was documented as safe and was not, which is worse than
being undocumented: it was checked and the check was reasoning rather than
measurement.

The coverage change is what makes growth mean anything. It converts "open a
desk" from a status flag into a countable obligation — thirteen jobs nobody
holds — and that count is a measured condition the M11 trigger table can fire
on. So the desks were staffed the way everything else here is decided: a
trigger, a proposal carrying the measurement, a prediction hashed before the
Board sees it, a decision, and an effect measured against the locked
prediction. Six desks, six Board meetings, thirty hires, all six predictions
`improved`.

**Thirty, not eighty.** Each desk got one generalist per department with
desk-specific charters, exactly as the launch roster staffed crypto. A desk
running on fixture data generates no load, and hiring one specialist per
charter to reach a headline number would have been the assumption `CLAUDE.md`
§16 exists to forbid — and that M11 measured and found false.

The roadmap's "100+" is therefore proved as what it actually is: **a claim
about the software, not about how many people the company chose to employ.**
A test hires into every one of the 154 slots, splitting the launch generalists
down through the company's own fission mechanism, and checks that the census
stays intact, that authority still resolves, and that the write-scope guards
still refuse. The company runs at 47. The machinery is shown to run at 154.

## Consequences

- The orphan guard keys on `(charter, desk)`. Keyed on the charter alone,
  handing over the Options Technical Analyst would have looked satisfied by
  the FX analyst still holding theirs, and the Options desk would have been
  left with nobody while the guard reported coverage intact.
- A desk-specific charter held by an agent with no desk **raises**. Defaulting
  would put every one of them on a single nameless desk and the census would
  read as complete.
- `Roster.coverage_of` returns deduplicated charter ids and `slots_of` returns
  the slots. Authority is per charter — a Technical Analyst has the same scopes
  on every desk — so the permission layer is unchanged, which is what ADR-0003
  promised and what this change tests.
- The launch roster's RISK agent now carries the crypto desk, because
  `risk.manager` is desk-specific: a risk manager manages the risk of a market,
  and at launch there is one.
- Backup goes through SQLite's backup API rather than a file copy, and restore
  **re-verifies** the chain and rehashes every artifact rather than reporting
  that a file opened.
- Postgres remains written and unexercised. It is stated as such in
  `docs/08-operations.md` rather than implied to work.
