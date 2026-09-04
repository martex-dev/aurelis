# ADR-0003 — Role fission is how the company grows itself

Status: accepted · 2026-09-04

## Context

The target is a company of 40+ agents at completion, expanding to hundreds as
it runs — with the expansion driven by the company itself, not by a human
editing a roster. Starting with 76 agents on day one would be unaffordable,
untestable, and would repeat the anti-pattern of building headcount before the
runtime works.

## Decision

**Separate the charter from the agent, and grow by splitting coverage.**

- A **Role** is a charter: the full remit. 76 charters are registered from day
  one (`docs/02-organization.md` §4).
- An **Agent** holds a **coverage set**: the subset of charters it currently
  stands in for.
- At launch, 17 agents cover all 76 charters. Every charter is owned; none is
  dropped.
- As measured triggers fire, the **Org Development Lead** proposes a
  **fission**: split a coverage set and hire a specialist for the split-off
  part.
- The reverse, **fusion**, merges agents whose outputs overlap or whose load no
  longer justifies two.

Triggers are measured, never guessed: backlog depth, response latency, quality
or calibration degradation, coverage starvation, output overlap, underuse, new
desk opened, scenario-suite failure.

Every change is an `OrgChange` carrying trigger evidence, a justification, a
**predicted effect**, and a measurement plan. A meeting decides. The effect is
measured afterwards and recorded — **including when the change made nothing
better.**

## Rationale

- The runtime never changes as the company grows. Agents are rows, roles are
  charters, desks are configs. 17 → 45 → 100+ is data, not code.
- Coverage is conserved by construction, and a test proves no charter area is
  ever orphaned by a split.
- It makes `CLAUDE.md` §16 concrete: "does 3 technical analysts outperform 2?"
  is answered by running the org experiment over the training-scenario suite
  and counting, rather than by assuming.
- Hiring becomes evidence-driven, which keeps cost proportional to demonstrated
  need — important while running on a subscription.
- **The company's structure gets a version history**, exactly like a strategy
  does.

## Consequences

- Launch agents must be honest about what they are: AG-04 holds nine
  Intelligence charters and its record says so. Its load metrics are the
  evidence for its own eventual split.
- Handover is real work: open tasks, channel membership and memory scope
  transfer on fission, and that path needs tests.
- Some org changes will be wrong. That is expected and is why the measurement
  plan is mandatory and the verdict is recorded either way.
- An agent may never modify its own record — not its coverage, not its
  permissions, not its metrics. Self-modification would make the growth
  mechanism unauditable.
