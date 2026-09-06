# ADR-0012 — Org changes are preregistered like research

Status: accepted · 2026-09-06

## Context

M11 gives the company the ability to change its own shape: split a role, merge
two, hire for a starved area. ADR-0003 already required every such change to
carry a predicted effect and a measurement plan.

What it did not say is **when** the prediction gets written down, or what stops
it being adjusted afterwards. Without an answer, the record degrades in the way
every unaudited reorganisation record degrades: after the fact, the change that
happened is described as the change that was intended, and the metric that
moved is described as the metric that was predicted. Every reorganisation
becomes a success, and the company learns nothing about its own judgement —
which is the one thing this whole subsystem exists to teach it.

The company already has the answer for research. A hypothesis is
**preregistered**: the specification, the analysis plan and the pass criteria
are hashed and locked before anything runs, and a registration revised after
results exist is automatically degraded to exploratory. The reason is exactly
the same, and it applies to the company with no adjustment at all.

## Decision

**An `OrgChange` is preregistered.**

1. The proposal names a metric from a **closed registry** of things the company
   can actually compute, a direction, a positive magnitude, and a plan for how
   the check will be made. A prediction naming something nobody can compute, or
   with a magnitude of zero, is refused at construction.

2. `lock()` hashes the prediction and the plan. After that, a database trigger
   refuses any update that changes the predicted metric, direction, magnitude,
   plan, window or digest.

3. **The lock happens before the Board convenes.** The room decides on a
   prediction it cannot influence.

4. `apply()` reads the baseline **immediately before** the structure moves, and
   records it on the row.

5. `measure()` reads the same metric after the declared window and records a
   verdict from a pure function — `IMPROVED`, `PARTIAL`, `NO_CHANGE`, `WORSE`
   or `UNMEASURABLE`. It is recorded whichever way it comes out.

## Rationale

The first demonstration is the argument. The company split two Intelligence
charters onto a dedicated agent: a sensible change, defensibly grouped, cleanly
handed over, coverage conserved, approved by a Board. It was sold on making the
generalist's outputs attributable per area.

It did not. Seven charters is as unattributable as nine, and the record says
`no_change`.

Under any looser scheme that would have been written down as a success —
something was split, the org chart looks more sensible, everybody agreed at the
time. It took a second change, splitting six more charters off, before the
metric moved. **The company needed two changes to buy what it thought one would
buy, and it can only know that because the first prediction was frozen before
anyone saw the outcome.**

## Consequences

- A proposal may only predict a metric in `orgdev.metrics.METRICS`. Widening
  what the company can predict about itself means adding a metric it can
  compute, which is the right thing to be forced to do.
- Metrics that cannot be taken are `None`, never zero, and **an unmeasurable
  reading never fires a trigger**. Reorganising because the instrumentation has
  a hole would be acting on the absence of a measurement.
- The baseline is read just before the change, not at proposal time and not
  after. The first implementation read it afterwards, which made a structural
  change invisible to itself — both sides of the comparison were post-change,
  and a split could never be seen to have split anything.
- An agent may not propose a change to its own record. This is a CHECK
  constraint (`subject_agent <> proposed_by`), not a convention.
- An applied or measured change must cite the meeting that decided it. Also a
  CHECK, and it originally named only `applied` — so a change's meeting could
  be cleared one state later and nothing complained. A guarantee that lapses
  one state after it is granted is not a guarantee.
- Some org changes will be recorded as failures. That is the intended output.
