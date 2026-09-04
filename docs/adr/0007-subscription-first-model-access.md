# ADR-0007 — Subscription-first model access

Status: accepted · 2026-09-04

## Context

There is no budget yet. The company should run on the existing Claude Pro
subscription while it is built, and cost should be as low as possible. A budget
may be set later, at which point per-token API accounting becomes relevant.

The architecture must not have to change when that switch happens.

## Decision

**A provider abstraction, with the subscription as the default implementation.**

```python
class ModelProvider(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse
    def cost(self, usage: Usage) -> Decimal
```

| Provider | Role |
|---|---|
| `agent_sdk` | Claude Agent SDK against the **Pro subscription** — the default |
| `anthropic_api` | Direct API with per-token money accounting — enabled when a budget exists |
| `cache` | Wraps either; keyed on pinned model version + prompt hash |
| `mock` | Deterministic replay — used by every test and all of CI |

Nothing above the provider layer knows which is active. The cost ledger records
both token units and money, so budgets, refusals and reporting work identically
either way.

**Model identifiers are pinned to exact versions.** An alias that silently
moved would make every cached response unreproducible while the cache key
stayed the same.

## The cost rules this implies

1. **Deterministic first.** Statistics, backtests, screening, ranking,
   correlation, portfolio math, and every Institutional Governance officer cost
   nothing. This is the largest lever by an order of magnitude.
2. **Tiered models.** High tier for Executive, Lead Researcher and Strategy
   Architect only. Mid for analysts, researchers, critics, reviewers, risk. Low
   for status turns, forecasts, monitors and routine briefings. None for
   deterministic officers.
3. **Meeting budgets.** Declared at convene, enforced per turn, tiered by
   phase. Running out of meeting is a normal outcome.
4. **Thin views.** An agent's prompt is its view, and permissions keep views
   small.
5. **Caching and replay.** Whole company-days replayable offline at zero cost.
6. **Deduplication.** Spec hash + data fingerprint: if the experiment ran,
   return the artifact.
7. **Hard budgets** per agent per day, per project, per mission, per company —
   refused at dispatch, before the call. Exhaustion is a recorded outcome, not
   a crash.
8. **Idle is free.** Agents are event-driven; a department with no work makes
   no calls.

## Consequences

- The whole system is testable and demonstrable at zero model cost via `mock`,
  which is what makes 100+ agents affordable to develop.
- Switching to a metered API is a config change plus a budget number.
- Subscription usage limits are a real operational constraint, so the scheduler
  must degrade gracefully: shed low-tier work first, defer non-mandatory
  meetings, and never drop a mandatory Kickoff or Retrospective silently — it
  raises an alert instead.
- Cost per accepted finding becomes a tracked company metric from day one,
  regardless of which provider is active.
