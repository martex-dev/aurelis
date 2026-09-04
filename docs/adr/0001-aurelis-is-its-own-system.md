# ADR-0001 — Aurelis is its own system; martex-quant and nullius are dependencies

Status: accepted · 2026-09-04

## Context

Two mature systems exist and were audited (`docs/00-audit.md`): **nullius**, an
artificial research institution, and **martex-quant**, a quantitative research
engine. An earlier draft proposed building Aurelis *as* nullius with a new op
registry. That was rejected.

Aurelis is a **corporation** — departments, desks, teams, meetings, careers,
self-expansion, multi-asset coverage. Neither existing system is that shape,
and neither should be stretched into it.

## Decision

**A new repository with its own architecture.** Both existing systems are
dependencies with strictly bounded roles.

**martex-quant** is a *tool inside the toolbox*: one research engine among
several (crypto), plus a validated data lake and a statistics library. It is
reached only through `engines/martex/`, in a subprocess with an explicit
workspace. It supports researchers with part of their work. It does not
generate hypotheses, decide anything, talk, or appear to any agent except as
tool calls.

**nullius** contributes two bounded things:
1. **Platform patterns** Aurelis implements in its own `platform/`: the
   hash-chained append-only event ledger, preregistration-before-run enforced
   by trigger, evidence typing, hierarchical money budgets, forecast scoring.
2. **One department** — Institutional Governance — whose eleven officers
   *serve* the other nine departments: they lock registrations, hold sealed
   data, type evidence, score forecasts, verify the chain, enforce budgets.

Institutional Governance has **no authority over research direction and
replaces nobody**. It is a service department, like compliance in a real firm.

Everything else — the corporation, the departments, the desks, the meetings,
the missions, the agent runtime, the station — is Aurelis's own architecture.

## Consequences

- Aurelis's design is free to be a company rather than a pipeline.
- martex-quant stays independently useful, unforked, and separately published.
- Dependency direction is one-way and enforced by layering: nothing in
  `engines/` or `governance/` knows the corporation exists.
- Cost: Aurelis reimplements platform pieces that nullius already has. Accepted
  — the patterns transfer even where the code does not, and owning the platform
  is what lets the company shape be first-class.
- Aurelis must earn its own integrity guarantees rather than inheriting them by
  import. The invariant tests (`docs/01-architecture.md` §14) are how.
