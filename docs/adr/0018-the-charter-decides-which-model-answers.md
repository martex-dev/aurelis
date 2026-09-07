# ADR-0018 — The charter decides which model answers

Status: accepted · 2026-09-07

## Context

Every one of the 76 charters declares a `ModelTier`, and `resolve_authority`
has computed an agent's tier since M1 as the highest among the charters it
covers. The meeting protocol declares a tier per phase. The price table knows
the three real models and which tier each belongs to.

None of it reached a model. Every call site in the company passed the literal
string `"mock-1"` — `decide_as`, `interpret_as`, the demo. The tier system was
a declaration with nothing downstream of it, and pointing the runtime at a real
provider would have asked Anthropic for a model by that name.

This is what stood between the company and its first real thought.

## Decision

**Routing is a function of (provider, tier), and the tier comes from the
charter.**

- `platform/llm/routing.py` maps provider × tier → model id. The mock answers
  every tier with `mock-1`; the subscription and the metered API share one
  ladder, haiku / sonnet / opus.
- `ModelTier.NONE` is **refused**, not routed. It covers seven charters and
  means the work is deterministic.
- Every routed model must be priced. The table is checked against `PRICES` at
  import, so a typo is a startup failure rather than a zero in the cost ledger.
- The seats that have an agent — the critic, the author, the reviser, and every
  bound `interpret` — pass **that agent's own tier**, resolved from its
  charters, rather than a default chosen by a function signature.
- A caller may still pin a model id. The router is the default, not a cage.

## Rationale

### Why routing is per provider

A table keyed only by tier would have to special-case the mock somewhere else,
and the entire offline test suite would start naming models nobody can call.
Keeping the mock a first-class row in the same table is what lets 700 tests
exercise the tier machinery at zero cost.

The two paying providers deliberately share one ladder. The same role should
get the same model whichever way the company is paying, or a cost experiment
would be measuring the payment method rather than the work.

### Why NONE raises

Returning the cheapest model for `ModelTier.NONE` would be the friendly thing
to do and it would be wrong. That tier means *no model is called* — a
deterministic officer, a statistic, a scheduled check. Routing it turns a
function call that should exist into a bill nobody notices, which is the
cheapest possible bug and the hardest to see. Reaching the router with NONE is
a defect in the caller and it should say so.

### What routing made visible

An agent's tier is the highest of the charters it holds, because it must be
capable of its most demanding role. At the launch roster that has a price:

```
76 charters      none=7  low=14  mid=48  high=7
17 agents        6 of them route HIGH because they hold one HIGH charter

25 charters are held by an agent that routes above the tier they were
   written for. AUDIT holds six charters spanning low, mid and high, so
   its cheapest work bills at fifteen times the rate that work needs.

 7 charters are NONE tier -- all held by GOV -- work that should call no
   model at all.
```

This is not an argument against generalists. It is a **measurable** cost of
them, and the company already has the machinery to act on it: fission (M11)
moves a charter to its own agent, and after a split the low-tier work routes
low. `aurelis model tiers` prints the whole picture, so the next fission
proposal can cite a number instead of an intuition.

## Consequences

- **The subscription path was exercised for the first time, and it failed
  honestly.** `claude-agent-sdk` installs, the provider reports available, the
  request is built and dispatched, and Claude Code answers: *Not logged in*.
  The wiring is real; the authentication is the operator's.
- **That failure arrived as a forty-frame traceback, and now does not.** SDK
  errors are translated into `ProviderUnavailable` with a sentence an operator
  can act on. Anything that is *not* a recognised SDK error is passed through
  unchanged — swallowing an unknown failure into "provider unavailable" would
  hide a real bug behind a reassuring message.
- **`availability()` was claiming more than it had checked.** It reported the
  subscription available on the strength of the package importing. Being
  importable is not being able to make a call, and `aurelis doctor` would have
  asserted something it had not tested. It now says login is unverified until
  `aurelis model check` runs.
- **Token counts now say whether they were measured.** `Usage.estimated` is set
  by the subscription provider, which counts characters when the SDK reports no
  usage. Budgets bind against these numbers, so a budget enforced on an
  approximation should not look like one enforced on a measurement.
- **A test parses the source and fails if any call site names a model
  literally.** The first version matched text and tripped on its own
  explanatory comments; it walks the AST now, so comments and docstrings that
  discuss the problem do not count as causing it.
- `aurelis model check` is the only command in the repository that reaches a
  provider, and it asks for confirmation before spending. Everything else stays
  offline.
- What is *not* done: no real model has answered anything yet, so nothing is
  known about whether the closed answer sets survive contact with one. That is
  the first thing to find out once login is in place.
