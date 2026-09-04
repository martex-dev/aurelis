# 07 — Implementation Roadmap

Date: 2026-09-04
Status: proposal, v2.

Every milestone ships something that runs and has an acceptance test. The
company is recognisably a company from M3 onward and grows from there.

---

## M0 — Foundations ✅

New repository. `martex-quant` from PyPI, `nullius` as a git dependency.

- `platform/` — database, migrations, event ledger with hash chain and
  append-only triggers, content-addressed artifact store, task queue, scheduler,
  budget ledger.
- `platform/llm/` — provider abstraction with `agent_sdk` (Claude Pro
  subscription), `anthropic_api`, `cache`, `mock`.
- `core/` — ids, config, clock, event types.
- `cli/` — `aurelis doctor`, `aurelis db init`, `aurelis ledger verify`.

**Acceptance:** `aurelis doctor` reports both dependencies healthy and the
database initialised. The ledger chain verifies. A mock provider runs a
scripted exchange end to end with zero API cost.

---

## M1 — The agent runtime ✅

- `org/` — department, desk, role and charter registries; the 76 charters
  loaded as configuration.
- `agents/` — agent record, permission resolution (read/write/tool scopes),
  view building, the agent loop, tool binding.
- `comms/` — messages, channels, mentions.
- One real agent working alone: an Intelligence agent that pulls crypto data,
  writes an observation, and posts a briefing.

**Acceptance:** an agent cannot read outside its view or write outside its
scope, proven by tests against raw SQL as well as through the runtime. Tool
calls are logged with cost. The agent's daily budget refuses work at dispatch
when exhausted.

---

## M2 — Missions, projects, tasks

- `missions/` — the three-level hierarchy, assignment, dependencies, progress,
  budget splits.
- Scheduler wired: daily briefings, data pulls, queue health.
- Three agents collaborating by message: Intelligence → Research → Analysis.

**Acceptance:** a mission decomposes into projects and tasks, work is assigned
and completed, and every artifact is traceable. A mission cannot leave
`PLANNING` without a kickoff (which M3 provides — until then the transition is
explicitly stubbed and tested as blocked).

---

## M3 — Meetings

The milestone that makes it a company.

- `meetings/` — the seven-phase protocol, the Chair (deterministic parts +
  Chief of Staff), turn recording and validation, evidence packs, forecast
  capture and scoring, objections with discriminating tests, decisions with
  dissent, action items into tasks, productivity metric.
- Meeting types: Kickoff, Standup, Brainstorm, Research Review, Retrospective.
- Mission state machine enforces Kickoff and Retrospective.

**Acceptance:** a mission opens with a kickoff meeting where agents genuinely
debate, produces a plan and assignments, runs, and closes with a retrospective
that writes lessons into memory. An unsourced numeral in a turn is rejected. A
meeting that produces no state change is recorded as unproductive. The whole
meeting runs inside its declared token budget.

---

## M4 — The research lifecycle and the engines

- `engines/` — the `ResearchEngine` protocol and the **martex adapter**
  (subprocess, explicit workspace): universe, data, features, backtest,
  statistics.
- `research/` — hypothesis, registration, experiment, run, result, finding,
  evidence, objection, replication; the state machine.
- `governance/` — Registrar (lock + hash), Evidence Officer, Forecast Scorer,
  Provenance Officer, Ledger Officer, Budget Officer.
- Preregistration triggers enforced against raw SQL.

**Acceptance:** a hypothesis goes from draft to a verdict with every number
traceable to an artifact hash. A run inserted without a prior locked
registration is refused by the database. The same spec and seed reproduce an
identical artifact hash. No agent can write a `Result` row.

---

## M5 — Critique, replication, and the Research Review

- Strategy Lab roles: Critic, Adversarial, Replication, Robustness, Validation.
- Market objection taxonomy with mechanical discriminating tests:
  `SURVIVORSHIP · LOOKAHEAD · COST_UNDERSTATED · LIQUIDITY_UNREALISTIC ·
  REGIME_SPECIFIC · CAPACITY_IGNORED · CROWDING · DATA_REVISION`.
- `universe.point_in_time` as a first-class engine operation.
- Integrity tools wrapped: `timeleak`, `leakguard`, `purged-cv`, `calibrate`.
- Audit department: research, data, backtest and agent-behaviour auditors.

**Acceptance — the target demonstration:** given the historical rotation
specification, the Critic raises `SURVIVORSHIP`, the discriminating test
dispatches inside a Research Review meeting, the point-in-time run returns
Sharpe 1.47 → 0.86, the author concedes on the record, and the hypothesis is
refuted — **with no human in the loop.**

That is martex-quant's H71 discovery, reproduced automatically by the company,
and it is the single most convincing thing this project can show early.

---

## M6 — Institutional memory and the knowledge graph

- `memory/` — lessons, standing rules, memory entries with computed confidence
  and confidence caps.
- Knowledge graph: nodes, edges, dependency and contradiction structure,
  independent-support with correlation discounting.
- Novelty and prior-art check on every new hypothesis.
- Import the martex-quant corpus: 174 trials, 72 hypothesis documents, existing
  graph edges — preserving published figures rather than recomputing them.
- Obsidian-compatible vault export, generated from the database, never edited
  back.

**Acceptance:** a Brainstorm's evidence pack automatically contains "we tried
this before" from the imported corpus. Ledger reconciliation reproduces the
corpus's own claimed totals. A finding's confidence degrades when an objection
opens against it.

---

## M7 — Mission Control, live

- `station/` — facility layout generated from the department and desk
  registries; the ten rooms plus Registry, Vault, Floor and Graveyard.
- Drill-down: company → department → agent → mission → meeting → hypothesis →
  experiment → artifact.
- Company timeline from the event stream; SSE live updates.
- `Figure(value, source)` with no source-less constructor; label-overlap test.
- Sealed static build retained.

**Acceptance:** run a full mission and understand what happened, who did it,
what it cost, what was decided, who disagreed and what failed — **without
opening a terminal, a source file or a raw log.** Every number on screen opens
its source.

---

## M8 — Strategy, portfolio, risk

- `strategy/` — registry, versions, immutability trigger, promotion gates A–G.
- `portfolio/` — construction, allocation, exposure, correlation, capacity.
- `risk/` — assessments, limits, veto, halts, kill latch; the three persisted
  numbers.
- Strategy Committee and Risk Committee meeting types.

**Acceptance:** modifying a `VALIDATED` version is refused by the database and
becomes a new version at `UNDER_REVIEW`. A trade proposal without a risk
assessment cannot be approved. A strategy that passes solo and fails gate C is
blocked, with the correlation evidence on the record.

---

## M9 — Paper trading

- `trading/` — proposals, approvals, orders, positions, post-trade.
- `BacktestBroker`, `SimulationBroker`, `PaperBroker`. **No `LiveBroker`.**
- Trading Operations roles; scheduled paper cycle; monitors and alerts.
- Backtest-live gap measured and forecast.

**Acceptance:** a validated strategy reaches paper only through the recorded
chain. The gap is measured daily and its forecast scored. A test asserts no
module imports martex-quant's MT5 adapter.

---

## M10 — Training scenarios and agent onboarding

- `engines/synthetic/` — market scenarios with planted effects: real premia of
  stated size, planted leaks, planted regime dependency, and scenarios
  containing nothing.
- Onboarding suite per charter; new agents are scored before they work.
- Playbook regression: a revision that lowers the catch rate fails CI.

**Acceptance:** a new agent's starting record is its scenario performance. An
agent that cannot catch planted defects in its own specialty does not start
work. Playbook changes are gated on the suite.

---

## M11 — Org development: the company grows itself

- Org metrics: load, latency, backlog, coverage starvation, overlap,
  calibration.
- `OrgChange` proposals with trigger evidence, predicted effect and measurement
  plan; Board meeting decides; effect measured afterwards.
- Fission and fusion implemented; handover of tasks, channels and memory scope.
- Org experiments run over the scenario suite: does adding an adversarial role
  reduce false discoveries? do three analysts beat two?

**Acceptance:** the company proposes, decides, applies and **measures** a
structural change to itself, and the result is recorded whichever way it comes
out. Total charter coverage is preserved across every fission and fusion, and
a test proves no charter area is ever orphaned.

---

## M12 — Multi-desk expansion

Desks open one at a time, each a repeatable sequence: register `DeskConfig`,
build or adapt the engine, wire data sources, define the cost and liquidity
model, set risk limits, staff it, run the scenario suite for the desk.

| Order | Desk | New engine work | Existing tools |
|---|---|---|---|
| 1 | CRYPTO | none — martex adapter | martex-quant |
| 2 | EQUITIES | prices, fundamentals, factor model | `factor-exposure` |
| 3 | OPTIONS | chains, IV surface, greeks | `vol-surface`, `implied-move` |
| 4 | FUTURES | continuous contracts, roll calendar | `roll-yield` |
| 5 | COMMODITIES | curves, seasonality, inventories | `roll-yield` |
| 6 | FX | bars, rate differentials, carry | — |
| 7 | MEMECOINS | launch cohorts, wallet persistence | martex-quant `meme/` |

**Acceptance:** each desk runs a complete mission end to end and its research
is comparable across desks in the ledger.

---

## M13 — Scale and hardening

Multi-worker execution, Postgres when concurrency demands it, failure recovery,
backup and restore, chain verification in CI, performance, deployment,
operator documentation.

Target shape: 80–100+ agents across seven desks, most charters held by
dedicated specialists, multiple agents per charter where load justifies it.

---

## Sequencing

```
M0 ─▶ M1 ─▶ M2 ─▶ M3 ─▶ M4 ─▶ M5 ─▶ M6 ─▶ M7 ─▶ M8 ─▶ M9
                    │            │                        │
                    │            └──▶ M10 ──▶ M11 ────────┤
                    │                                     │
                    └─────────────────────────────────────┴──▶ M12 ─▶ M13
```

Three deliberate orderings:

1. **Meetings at M3, before research.** They are the company's core mechanic,
   and every later subsystem should be built to be discussed in one.
2. **Integrity at M5, before strategies exist.** A company that produces
   results faster than it can check them produces false discoveries faster.
3. **The station at M7, before strategy and trading.** Every later milestone
   then has to render itself into an existing station, which is what keeps the
   UI honest. Built last, it becomes a veneer.

---

## Headcount by milestone

| Milestone | Agents | Desks |
|---|---|---|
| M1 | 1 | CRYPTO |
| M2 | 3 | CRYPTO |
| M3 | 8 | CRYPTO |
| M5 | 17 (launch roster) | CRYPTO |
| M8 | ~22 | CRYPTO |
| M11 | ~28 | CRYPTO + EQUITIES |
| M12 | 45 → 80 | 3 → 7 |
| M13 | 100+ | 7 |

The full 76-charter roster is covered from M5 onward — first by generalists,
then increasingly by specialists as the company splits its own roles on
measured evidence.

---

## Cost posture

Everything runs on the Claude Pro subscription through the `agent_sdk`
provider until a budget is set. That constrains the design in useful ways and
each is already in the architecture:

- Deterministic-first: statistics, backtests, screening, ranking, portfolio
  math and every Governance officer cost nothing.
- Tiered models: high tier only for Executive, Lead Researcher, Strategy
  Architect. Low tier for status, forecasts, monitors and routine briefings.
- Meeting budgets declared at convene and enforced per turn.
- Caching and replay: whole company-days replayable offline at zero cost.
- Idle is free — event-driven agents make no calls when there is no work.
- Mock provider for all tests and all CI.

When a budget is set, switching to `anthropic_api` is a config change and the
cost ledger already accounts in money.
