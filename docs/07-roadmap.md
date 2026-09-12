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

## M2 — Missions, projects, tasks ✅

- `missions/` — the three-level hierarchy, assignment, dependencies, progress,
  budget splits.
- Scheduler wired: daily briefings, data pulls, queue health.
- Three agents collaborating by message: Intelligence → Research → Analysis.

**Acceptance:** a mission decomposes into projects and tasks, work is assigned
and completed, and every artifact is traceable. A mission cannot leave
`PLANNING` without a kickoff (which M3 provides — until then the transition is
explicitly stubbed and tested as blocked).

---

## M3 — Meetings ✅

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

## M4 — The research lifecycle and the engines ✅

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

## M5 — Critique, replication, and the Research Review ✅

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

## M6 — Institutional memory and the knowledge graph ✅

- `memory/` — lessons, standing rules, and confidence **derived on read** with
  every cap and its reason. Confidence is a band (NONE · WEAK · MODERATE ·
  STRONG), never a stored number: a column would need somebody to remember to
  update it, and the one time that mattered would be the time nobody did.
- Knowledge graph: nodes, edges, dependency and contradiction structure,
  independent-support with correlation discounting. The graph assigns no
  confidence of its own, and the discount **reports what it discounted**.
- `memory/mirror.py` projects the research record onto the graph. A projection,
  not a second copy — it draws only relationships the record already states,
  and every derived edge is signed `mirror` so it is distinguishable from one
  an agent asserted.
- Novelty and prior-art check, deterministic (no model call, no embedding) over
  the company's own hypotheses and every imported corpus at once. It
  distinguishes *searched and found nothing* from *nothing to search*.
- Import the martex-quant corpus, preserving published figures rather than
  recomputing them.
- Obsidian-compatible vault export, generated from the database, never edited
  back. The module offers no function that could read one — asserted by a test.

**Which corpus, and why the numbers differ.** The audit counted **174 trials**
in the martex-quant *repository*. The corpus bundled inside the installed
*wheel* is an earlier snapshot claiming **125** (124 run, 1 data-blocked) across
21 entries and 29 hypothesis documents. Both figures are right about different
artifacts, and the importer reads either:

```
aurelis memory import                          # the wheel's snapshot: 125 claimed, 120 documented, 5 carried
aurelis memory import --bundle <repo>          # the live repository:  174 claimed, 169 documented, 5 carried
```

The default is the wheel, so an import is reproducible from the lockfile alone.
The reconciliation row stores the SHA-256 of whichever ledger was read, so
"which corpus is loaded?" is always answerable and a corpus that changed under
a re-import is detectable rather than silently merged. The five-trial gap
survives both — it is a property of the research record, not of the snapshot.

**Acceptance — met:**

| | |
|---|---|
| Brainstorm evidence pack contains "we tried this before" | `memory/brainstorm.py` searches before the room opens; the pack is stored as an artifact, so what everyone saw is citable |
| Ledger reconciliation reproduces the corpus's claimed totals | Claimed = documented + carried, on both corpora. The gap is not distributed — the source itself says doing so "would be fabrication" |
| A finding's confidence degrades when an objection opens | MODERATE → WEAK on an open major objection, → NONE on a critical or an upheld one, and back when it resolves |

Two figures are preserved rather than recomputed: `dsr` alongside the
`dsr_n_trials` it was actually deflated against (0.99 against 65, not against
today's count), and `dsr_published` holding the literal text, because the money
column pads the scale to eight places and "as published" has to survive a
database round-trip.

---

## M7 — Mission Control, live ✅

- `station/` — facility layout generated from the department and desk
  registries: ten department rooms, the Registry and the Vault (no corridor),
  the Floor with a bay per desk, and the Graveyard. Fixtures are placed by a
  hash of each room's id, so two builds of the same state produce the same
  picture. Staff figures are drawn from the **headcount**, not from scenery.
- Drill-down: company → department → agent → mission → meeting → hypothesis →
  registration → run → measurement → artifact digest.
- Company timeline from the event stream, with SSE live updates.
- `Figure(value, source)` with **no source-less constructor** — `Figure(42)` is
  a `TypeError`, and a test asserts it. Every caption carries its own box and a
  test asserts that no two overlap.
- Sealed static build: one file, no external requests, stamped with the ledger
  head and the chain verification result.
- Served by the standard library rather than FastAPI
  ([ADR-0009](adr/0009-the-station-is-served-by-the-standard-library.md)),
  which makes read-only structural: the handler implements `do_GET` and nothing
  else, so there is no code path through which the station can write.

**Acceptance — met.** `test_the_whole_review_is_legible_without_a_terminal`
runs the M5 review and then reads the answers off rendered pages: what happened
(`REFUTED`), what failed (`survivorship`, upheld), the measurement that killed
it (`0.64507263`), why it was believed (`REG-0001`, the criteria committed
before the run, the data fingerprint, `computed_by = ENGINE`), who did it
(the agent page, with what it may see and write), what was decided and who
disagreed (the transcript, decision and dissent), and what it cost.

**What M7 does not deliver, stated rather than implied.** The station is
read-only. It delivers *understand* without a terminal, which is what the
criterion above asks; *operate* without a terminal needs the write surface, and
that arrives with the milestones owning those decisions (M8 risk, M9 paper
trading, M11 org changes). Rooms for records that do not exist yet read
`NO DATA — arrives in M8` rather than `0`, because a zero would be a fabricated
fact about a world nobody looked at.

---

## M8 — Strategy, portfolio, risk ✅

- `strategy/` — **components, compositions and lineage**; versions, the
  immutability trigger, promotion gates A–G. A strategy is composed from pieces
  agents authored, never promoted from a result
  ([ADR-0010](adr/0010-strategies-are-composed-not-promoted.md)).
- `strategy/markets.py` — what each of the seven desks structurally provides,
  derived from the desk registry. A component declares what it *assumes*;
  a desk that cannot meet it is `INAPPLICABLE`, not merely untested.
- `portfolio/` — construction, allocation, exposure, measured correlation,
  concentration. Separate from risk so the two can disagree.
- `risk/` — assessments, limits, veto, halts, kill latch; the three persisted
  numbers. `approve()` takes no exposure argument.
- Strategy Committee and Risk Committee meeting types. The Strategy Committee
  gets a CHALLENGE phase: "gate C measured correlation over 90 days, re-measure
  over 365" is a discriminating test, and a promotion meeting that could not
  run it would be deciding on an argument it had no way to end.

**Creation, not selection.** The distinction the milestone is built around:
there is no `promote_hypothesis`, no `from_finding`, and no `hypothesis_ref` on
a version — a test asserts the absence of each. `Origin.DERIVED_FROM_FAILURE`
is the only bridge from research, and it makes a refuted hypothesis *material*
rather than a candidate. `Synthesis.novelty()` counts origins, so "did the
agents create this?" is measured rather than claimed.

**Seven markets, not one.** The inherited corpus was measured on crypto alone.
Every version is native to exactly one desk and `UNPROVEN` on the other six
until measured there; claiming `PORTED` requires evidence from a run on that
desk.

**Acceptance — met:**

| | |
|---|---|
| A `VALIDATED` version cannot be modified | The trigger refuses the `UPDATE` against raw SQL; a material change becomes a new version at `UNDER_REVIEW` with the parent untouched |
| A proposal without a risk assessment cannot be approved | Refused by the service *and* by a trigger that also rejects an approval borrowing another proposal's assessment, or exceeding the size Risk allowed |
| Gate C blocks a strategy that passes solo | Six gates pass, C fails at a measured 0.83 against a registered bound of 0.5, and the correlation stays on the record |

---

## M9 — Paper trading ✅

- `trading/` — orders, fills, positions, post-trade reports and gap
  measurements. Proposals, assessments and approvals arrived with M8's risk
  layer; M9 adds the half that reaches a broker.
- `BacktestBroker`, `SimulationBroker`, `PaperBroker`. **No `LiveBroker`** —
  no adapter, no `BrokerKind` member, no registry entry, and `resolve("live")`
  refuses with an explanation rather than a `KeyError`.
- `alerts/` — raise, acknowledge, resolve, with acknowledgement and resolution
  as separate acts. Open alerts deduplicate while unresolved.
- `PaperCycle` runs the whole chain in order and records what it refused.
- Backtest-live gap measured against the artifact digest of the number that
  justified deployment, with a scored forecast per deployment.
- **The write-scope guards M8 promised.** `trade_proposals`,
  `risk_assessments`, `trade_approvals` and `orders` are four different scopes
  held by four different roles, so "the agent that wants the exposure is not
  the one that approves it" is enforced by the database. Components, strategy
  versions, gates and allocations are guarded too.

**Acceptance — met:**

| | |
|---|---|
| Paper only through the recorded chain | An order's approval FK is non-nullable, and a trigger re-checks the approval still cites a permitting assessment of its own proposal. A second trigger caps the notional at what Risk approved |
| The gap is measured and its forecast scored | Expectation copied from the supporting run with its artifact digest; a deployment forecasts whether its backtest will hold and the first period scores it with a Brier |
| No module imports the MT5 adapter | `test_no_module_imports_the_live_broker_adapter`, now parsing imports rather than grepping for a substring |

**Two bugs the demonstration caught that reading did not.** Money is stored as
text so it round-trips exactly, and SQLite compares an integer to a string by
type class rather than value — so `12000 > '5000.00000000'` is false and
`'1000.00000000' >= 0` is *true*. Several CHECK constraints were therefore
vacuous and one trigger silently permitted every oversized approval it existed
to stop. Every money comparison now casts, and the trap is documented on the
`Money` type itself. Separately, the gap's `held` compared `realised - expected
>= 0` for every metric, which reported a deployment that *beat* its drawdown
estimate as having fallen short; direction is now read from an explicit table
that raises on an unknown metric rather than guessing.

---

## M10 — Training scenarios and agent onboarding ✅

- `engines/synthetic/` — twelve worlds built from recipes: a genuine momentum
  premium, names that drift up and delist, an effect confined to one regime, a
  run inside the priming window, an edge the width of the spread — and three
  with nothing planted in them at all.
- **Truth is measured, not authored.** A recipe is an instruction, not a claim.
  Each world is drawn twenty-four times and the answer is whatever replication
  finds. Where it disagrees with what the author intended, the disagreement is
  reported and kept.
- `training/` — playbooks (a charter's critique procedure, as versioned
  thresholds over the closed defect taxonomy), the suite that runs one over
  every scenario, the marking, the onboarding record and the regression gate.
- The onboarding gate is a **trigger on `agents`** — the first `BEFORE UPDATE`
  invariant in the system, because state lives in an update.

**Acceptance — met:**

| | |
|---|---|
| A new agent's starting record is its scenario performance | `staff()` routes through `Onboarding`; every hire gets a `TrainingRun` citing the catalogue digest, the playbook digest and a per-scenario mark |
| An agent that cannot catch planted defects does not start work | A blunted procedure fails the standard and the database refuses the transition to `active`, against raw SQL |
| Playbook changes are gated on the suite | `aurelis training regression` runs in CI on all four matrix jobs, and CI also asserts the gate rejects a deliberately weakened procedure |

**Three things the suite found in its first run**, all of them in code that had
shipped and been tested:

1. **`COST_UNDERSTATED` was unfalsifiable.** It read as *present* in all three
   worlds with nothing planted in them, because tripling the cost of a rule
   that trades makes it worse whether or not it ever had an edge. Mechanical
   tests are now **corrective** or **stress** (ADR-0011), and a stress
   objection against a specification that never showed a result settles
   nothing.
2. **The `LOOKAHEAD` test was a provable no-op.** Its warm-up was one lookback,
   and every registered signal already holds nothing during its own lookback —
   so the varied run was byte-identical to the original for every specification
   the objection had ever been raised against.
3. **A scenario's digest did not include its world.** Two scenarios presenting
   the same specification over different plants hashed identically, and the run
   cache served one's artifacts for the other. Caught because every candidate
   in a tuning sweep returned the same numbers.

**What is honestly not there.** `CAPACITY_IGNORED` has no scorable scenario:
the plant is in the catalogue, measurement says it did not take, and settings
that did report it flipped their answer between 24 and 40 replications, which
is not a verdict. The suite reports the hole. And what is scored today is the
**procedure a charter issues**, not an agent's own judgement — agents do not
yet reason their way through a critique. The harness does not change when they
do; the playbook is replaced by the agent and the same twelve worlds mark the
same twelve answers.

---

## M11 — Org development: the company grows itself ✅

- `orgdev/metrics.py` — load, backlog age, throughput, breadth, calibration,
  scenario record, coverage starvation. **A metric that cannot be taken is
  absent, never zero**, and an unmeasurable reading never fires a trigger.
- `orgdev/detection.py` — the declared trigger table from §6.2 of
  `docs/02-organization.md`, as code. `BREADTH` fires first and hardest,
  because seventeen agents standing in for seventy-six charters is the launch
  roster's defining condition.
- `orgdev/development.py` — propose, **lock**, decide, apply, measure. The
  prediction is hashed before the Board convenes and frozen by a trigger
  afterwards (ADR-0012).
- `orgdev/handover.py` — fission and fusion. **Coverage moves by a single
  UPDATE**; it is never deleted and recreated, so no charter is held by nobody
  at any instant and none by two people.
- `orgdev/experiments.py` — panels over M10's twelve worlds. `CLAUDE.md` §16
  as arithmetic.
- `MeetingType.BOARD`, the first meeting whose subject is the organisation.

**Acceptance — met:**

| | |
|---|---|
| The company proposes, decides, applies and measures a change to itself | `aurelis orgdev develop` runs two, end to end: trigger scan → proposal → lock → Board → apply → handover → onboarding → measure |
| The result is recorded whichever way it comes out | The first change is recorded `no_change`. It failed |
| Coverage is preserved across every fission and fusion | A census test after each; and the database refuses to orphan a charter, including via the cascade from retiring an agent |
| No charter area is ever orphaned | `test_the_database_refuses_to_orphan_a_charter`, `test_retiring_an_agent_cannot_take_its_coverage_with_it` |

**The demonstration's first change failed, and that is the result.** Splitting
news and sentiment off the Intelligence generalist was sensible, cleanly handed
over and Board-approved — and the thing it was sold on, making that agent's
outputs attributable per area, did not happen. Seven charters is as
unattributable as nine. It took a second change, splitting six more off, before
the metric moved. Under any looser scheme the first would have been written
down as a success.

**Two bugs the demonstration caught that reading did not.**
`attributable_charters` was `None` for every generalist, which made it useless
as a prediction target — a change could not move it from unmeasurable to
unmeasurable, so the verdict was always `UNMEASURABLE`. A metric a change
cannot move is not a metric; it is now a genuine count with a measured zero.
And the baseline was read *after* the structure changed, which made a
structural change invisible to itself: both sides of the comparison were
post-change, and a split could never be seen to have split anything.

**What the org experiments actually found.** Adding an adversarial researcher
to a research panel took catches from 4 to 7 with no more false alarms — but
not because it is adversarial: because its specialty covers three defects
nobody else in the room was asked about. Adding a *second* critic with the same
specialty moved nothing at all, and three narrow specialists whose specialties
union to a generalist's scored exactly what the generalist scored. **More
agents help only when they widen what the room is asked.**

---

## M12 — Multi-desk expansion ✅

All seven desks open, each through the same evaluated checklist:
`desks/readiness.py` runs nine checks against the live system and **refuses**
a desk that fails any of them.

- `desks/calendars.py` — four trading clocks. 8760 hourly bars a year on 24/7,
  **1638** on the NYSE, 5796 on CME, 6240 on 24/5. Declared per calendar, not
  derived, and an undeclared interval raises rather than guessing.
- `desks/costs.py` — a cost model per asset class, split into per-trade,
  per-holding-period, per-contract and impact. 40bps a round trip on crypto,
  760 on memecoins. Carry is charged on **time held**, so a slow strategy
  cannot escape funding.
- `desks/comparability.py` — annualisation through the desk's own calendar,
  with the factor recorded, and refusals for what cannot be joined.
- `desks/power.py` — how much data a claim needs, per desk.
- `desks/limits.py` — leverage and concentration as policy; the position
  ceiling read off the desk's own liquidity.
- `desks/sources.py` — a fixture universe per desk, on that desk's calendar,
  at that desk's tick, each with its own casualties.

**Acceptance — met:**

| | |
|---|---|
| Each desk runs a complete mission end to end | `aurelis desk compare` drives propose → screen → preregister → design → run → conclude on all seven, each with its own calendar, costs, universe and casualties |
| Research is comparable across desks | Every figure converted through its own desk's calendar with the factor printed beside it; the ranking changes once converted |

**The comparability half did not work before, and the reason looked like a
formatting detail.** The engine reported Sharpe as `per_bar`, which was honest
and useless: the same 0.05 is an annualised 4.7 on crypto and 2.0 on the NYSE,
so an archive ranking them together would rank by sampling frequency. The
widest pair of desks differ by a factor of **2.31**.

**The finding that came out of stating claims properly.** A claim is worth
stating annualised. Converting it down to a desk's per-bar minimum effect
divides by `sqrt(periods per year)`, so a fast-sampling desk chases a smaller
effect and needs more bars — and the two cancel exactly. Settling an annualised
Sharpe of 1 takes **the same 3.84 years on every desk**, and 33,655 hourly bars
on crypto against 6,295 on equities. So **a research budget stated in bars is
not a budget**: the same number gives crypto seven weeks and equities nine
months, and underpowers whichever desk samples fastest while looking
even-handed. Budgets are now stated in years.

**Two silent bugs the fixtures caught.** Tick size is a desk property: at a
cent tick an FX rate of 1.00 never moved and a memecoin priced at four
thousandths of a cent quantized to zero, so two of seven desks produced
perfectly flat series — and the engine ran, the metrics computed, and the
verdict rule said `UNDERPOWERED` without anything reporting the input had been
a constant. "Prices move" is now a readiness check that fails the desk.

**What is honestly not there.** No desk has a live data feed; every one runs on
fixtures, which the checklist records as `PROVISIONAL` rather than a pass, and
which every desk page and every artifact repeats. The options desk is open and
the local engine cannot compute a single greek — a typed refusal, so that desk
is researchable as a price series and not as an options book. All seven
verdicts came back `UNDERPOWERED`, correctly: a quarter of data against a claim
needing 3.84 years.

---

## M13 — Scale and hardening ✅

- `org/slots.py` — **coverage is `(charter, desk)`**. ADR-0004 promised the
  second dimension and nothing implemented it: `Charter.desk_specific` existed
  and nothing read it. Thirteen charters are desk-specific, so seven open desks
  means **154 slots**, not 76.
- `orgdev/staffing.py`, `orgdev/scaling.py` — the desks staffed through the M11
  lifecycle. A measured trigger, a proposal carrying the measurement, a
  prediction hashed before the Board, a decision, an effect measured.
- `platform/backup.py` — consistent snapshots through SQLite's backup API, and
  a restore that **re-verifies** the chain and rehashes every artifact.
- The task claim is a **compare-and-set** (ADR-0014).
- `docs/08-operations.md` — how to run it, what to check, what breaks, and what
  it cannot do.

**Acceptance — met:**

| | |
|---|---|
| Multi-worker execution | Eight threads, forty tasks, one claim each — asserted with real threads |
| Backup and restore | Round trip verified against a manifest; a tampered artifact is refused |
| Chain verification in CI | `aurelis ledger verify` and `aurelis db verify` both run |
| Operator documentation | `docs/08-operations.md`, and every command it names is exercised in CI |
| Target shape: 100+ agents across seven desks | Proved at **154** — one agent per slot — with coverage intact, authority resolving and the write-scope guards still refusing |

**The queue was doing work twice, silently.** `claim` selected a task and then
wrote `CLAIMED` onto it, documented as safe because of Postgres' `SKIP LOCKED`
and SQLite's single-writer model. The second half was false: SQLAlchemy opens a
DEFERRED transaction on SQLite, so the SELECT took no lock. Eight workers
against forty tasks produced **fifty-three claims and no error** — thirteen
tasks done twice, each drawing its own budget. The write is now conditional on
the row still being queued and the affected-row count decides, which is correct
on every dialect and does not depend on an isolation level.

**The company grew to 47, not 80.** Each desk got one generalist per department
with desk-specific charters, exactly as the launch roster staffed crypto. A
desk on fixture data generates no load, and hiring a specialist per charter to
reach a headline number is the assumption §16 exists to forbid. So "100+" is
proved as what it actually is — a claim about the software rather than about
headcount — by a test that hires into all 154 slots and checks nothing breaks.

**What M13 did not do**, stated in full in `docs/08-operations.md` §9: no live
data feed on any desk, no desk-specific training scenarios, Postgres written
and unexercised, no automatic recovery of a dead worker, and agents that still
do not reason their way through a critique.

---

## M14 — Agents that decide ✅

Past the roadmap, toward the two objectives it was written to reach.

M10 built the instrument for measuring judgement and scored a **procedure** —
numeric thresholds over the closed defect taxonomy. Its own docstring named the
gap: the harness would not change when agents reasoned for themselves, the
playbook would simply be replaced by the agent. This is that replacement.

- `agents/decide.py` — a `Question` with a closed option set, an answer that is
  **parsed rather than interpreted**, `NOTHING` always available, and the same
  figure check prose is held to.
- `training/critic.py` — an `AgentCritic` interface-compatible with a
  `Playbook`, run over the same bench, the same draw and the same marking.
- `training/seating.py` — the two weighed against each other by the M10 gate.

```
playbook       caught 7/8, false alarms 1/31
agent          caught 8/8, false alarms 8/31
the gate       REFUSED
```

**The agent caught everything the suite plants**, including the defect the
shipped procedure misses — and raised objections against eight specifications
that did not have one. The gate compares on counts and refused it. Finding more
is not the same as being better, and the company declined on arithmetic rather
than on taste. Restricted to survivorship alone, where the same agent catches
all three planted cases and raises nothing spurious, it ships.

**What sits behind the seat here is not a model.** Every model call in this
repository runs against the mock provider, so a deterministic stand-in supplies
the answers; what is exercised is the machinery — the closed option set, the
parse, the figure check, the refusal path, the scoring and the gate. Point the
runtime at a real provider and the same code path asks a real model. Every
report of a seating says so.

Building the stand-in caught a bug of exactly the kind this layer exists to
catch: its headline regex was anchored to the line after the section heading,
`render_material` sorts a section's keys, and the caveat line sorts above the
measurement. It matched nothing, **every stress defect was suppressed on every
scenario**, and the result read like a considered difference of judgement
rather than a broken regex.

---

## M15 — An agent authors a strategy ✅

The seat the project was started for. M14's agent judged a specification
somebody else wrote; this one writes it.

M8 built the surface — `author_component`, `compose`, a required rationale, a
citable origin, and deliberately **no** function that promotes a hypothesis
into a strategy. What it did not have was an agent: until now the pieces were
written by hand in a test fixture, so "agents write pieces" was true of the
software and not of the company.

- `authoring/design.py` — five slots over **72 reachable designs**, enumerated
  by walking the branch structure rather than multiplying slot widths.
- `authoring/author.py` — the agent answers every field the synthesis surface
  requires: the design, the rationale, the origin, the weaknesses.
- `authoring/attempt.py` — the whole sequence, preregistered and measured.

```
design      momentum, one-week lookback, two-percent threshold, long only
returned    2.6%          holding the asset returned 24.3%
cost drag   9.2%          the design paid it and did not earn it back
verdict     UNDERPOWERED  settling the claim needs ~15 years of hourly bars
declared    72 cells      the space it chose from, not the design it picked
```

**The authored strategy did not beat holding the asset**, the company says so
as the headline, and no part of the pipeline is arranged to avoid saying it.

### Why the whole space is declared

Authoring from a menu is cheap. A company that lets an agent author until
something passes has built a parameter miner with a rationale field attached —
and the rationale makes it worse, because it makes the mining legible as
reasoning. So `declared_cells` is 72, not 1: the agent was shown the
alternatives and nothing in the record can establish which it implicitly
weighed, and a false-discovery denominator faced with an unmeasurable quantity
has exactly one defensible direction. A second attempt costs the family a
second 72.

Costs, universe and warm-up are not slots. Those are three of the defects M10
scores the company's own critic on catching, and an authoring surface that
offered them would have the two halves of the company working against each
other by design.

### The slot that changed nothing

Sweeping the candidate space before writing it down, every rotation design
returned an **identical Sharpe for all three thresholds** — the cross-sectional
signal never read the parameter. A knob hashed into a specification, charged to
the denominator and justified in an agent's own words, that cannot change any
number, is decoration; and decoration in a preregistration is worse than
absence, because it makes the search look wider than it was. The engine gained
the parameter (defaulting to the zero it always used), and the sweep is now a
test that fails if any choice in any slot stops mattering.

See [ADR-0016](adr/0016-authoring-is-a-search-and-the-search-is-declared.md).

---

## M16 — A search budget, declared and then subtracted ✅

M15 authored once and stopped, and wrote down why: a revision loop is where
authoring turns into mining, and it should not be added without deciding first
what stops it. This is the loop with the rule attached.

- `authoring/campaign.py` — a budget and a criterion, hashed and locked before
  the first design exists.
- `authoring/invariants.py` — a trigger that refuses to change either once an
  attempt has run. A budget raised after seeing the results is not a budget.
- `authoring/revision.py` — two closed questions: which one slot changes, and
  what it becomes. Recorded through `mutate`, so the lineage is real.
- `authoring/selection.py` — the best result minus what a search of that width
  returns from noise alone.

```
attempt 1   one-week lookback      sharpe  0.0050   return  0.026
attempt 2   three-day lookback     sharpe  0.0260   return  0.202   <- best
attempt 3   one-day lookback       sharpe -0.0342   return -0.209
attempt 4   six-hour lookback      sharpe -0.0674   return -0.226
attempt 5   + half-percent floor   sharpe -0.1002   return -0.547

best observed        0.0260   and it beat holding the asset
expected best of 96  0.0538   from noise alone
surplus             -0.0278   the campaign found nothing
```

**Revising moved the number.** The second attempt beat buy-and-hold on its own
window, which M15's single attempt did not — and a report that stopped there
would be a discovery. The correction says it is still below what a search of
this width returns when there is nothing to find. Four of the five attempts are
worse than the one before: the campaign is a walk, not a convergence, and one
point on it happened to be high.

### What the budget buys

Inside a declared campaign, and only there, the agent may see its own result.
Everywhere else an author is shown structure alone. That is not a relaxation of
the preregistration rule: the rule has two halves, and the half that protects
the number is not *when* the choice was made but *how wide* the search was.
**Learning from a result is allowed exactly to the extent that the learning was
budgeted for.**

### The stronger version of the same finding

Sweeping the whole authorable space says it without any agent involved: the best
of all 72 designs measures 0.0274 against an expected best of 0.0516. Six trials
is enough to eat it. The answer to "should we search harder?" is that searching
harder raises the bar faster than it finds anything.

See [ADR-0017](adr/0017-a-search-budget-is-declared-and-then-subtracted.md).

---

## M17 — The charter decides which model answers ✅

The first of the four milestones toward running the company on a real model.

Every charter declares a `ModelTier`, `resolve_authority` has computed each
agent's tier since M1, and the price table knows which model belongs to which
tier. **None of it reached a model.** Every call site passed the literal string
`"mock-1"`, so pointing the runtime at a real provider would have asked
Anthropic for a model by that name.

- `platform/llm/routing.py` — provider x tier -> model id, with `NONE` refused
  and every routed model checked against the price table at import.
- The seats pass **the agent's own tier**, resolved from its charters, rather
  than a default chosen by a function signature.
- `aurelis model routes` / `tiers` / `check` — the table, the consequence, and
  the one command in the repository that reaches a provider.

### What routing made visible

```
76 charters      none=7  low=14  mid=48  high=7
17 agents        6 route HIGH because they hold one HIGH charter

25 charters are held by an agent that routes above the tier they were
   written for. AUDIT spans low, mid and high, so its cheapest work
   bills at fifteen times the rate that work needs.
 7 charters are NONE tier, all held by GOV: work that should call no
   model at all.
```

Not an argument against generalists — a **measurable** cost of them. Fission
(M11) moves a charter to its own agent, and after a split the low-tier work
routes low. The next fission proposal can cite a number rather than an
intuition.

### The subscription path, exercised for the first time

`claude-agent-sdk` installs, the provider reports available, the request is
built and dispatched, and Claude Code answers **Not logged in**. The wiring is
real; the authentication is the operator's. Three things changed because of it:
the SDK's errors are translated into `ProviderUnavailable` with a sentence
instead of a forty-frame traceback; `availability()` stopped claiming a login
it had not checked; and `Usage.estimated` now says whether token counts were
measured or guessed, because budgets bind against them.

See [ADR-0018](adr/0018-the-charter-decides-which-model-answers.md).

---

## M18 — The seats meet a real model ✅

M17 routed the charter's tier to a real model. The subscription was signed in,
and for the first time something other than a scripted stand-in sat in one of
this company's seats.

**The first five samples produced zero usable answers.**

```
0: ABSTAINED   "fixture data rather than live market data ... too short"
1: UNSOURCED   cited 91    (three months, derived from 2190 hourly bars)
2: ABSTAINED   "neither the sample nor the live data to support a claim"
3: ABSTAINED   "2190 bars ... about 3 months ... there is neither the ..."
4: UNSOURCED   cited 0.25  (2190 out of 8760, derived)
```

Neither failure was the model behaving badly. **It abstained because our own
honesty told it to** — the material truthfully says the data is a fixture and
only 2190 bars, and a careful model declines to claim an edge on that. **It
derived because the instruction invited it** — "cite only figures shown above"
reads as *reason only from these*, so it wrote `0.40%` for the 40 bps it was
shown.

Both were fixed by saying what was meant, and **no guard was widened**:

- `FIGURE_RULE` states the rule exactly — numbers must appear as written, no
  conversions, no ratios — and is appended wherever the guard applies.
- The authoring prompt now says what the seat is: choosing a design is *not* a
  claim that it works; the data may be short or synthetic and that is a fact
  about the experiment, not a reason to decline.
- `platform/llm/rehearsal.py` makes conformance a number rather than an
  impression: `aurelis model rehearse --seat author|critic`.

Both seats afterwards: **5/5 usable**.

### What a real model then did

Reasoning only from the cost and the bar count, with no access to any result, it
picked momentum / three-day lookback / half-percent threshold / long-only — the
**highest-Sharpe design of all 72** — and beat buy-and-hold, 0.233 against
0.152.

That was one sample. A later campaign from the same model took the rotation
branch and all four attempts were negative. The correction is unmoved either
way: 0.0274 against an expected best of 0.0516 for a search that wide.

### Three things that only broke once a model was real

- Every report kept printing "the designer behind this seat is a deterministic
  stand-in" **while a real model answered**. The caveat is now resolved from
  the provider and carried on the outcome.
- A revision **reverted onto a design already measured** — correctly, having
  been told its change did worse, but spending a declared cell to re-learn a
  known number. Revisions now see the campaign's whole history, and an exact
  repeat is refused.
- Running out of subscription allowance arrived as a traceback. It now reads as
  a sentence that says when the limit resets.

See [ADR-0019](adr/0019-the-seats-meet-a-real-model.md).

---

## M19 — The company pays for its own shape ✅

M17 gave every charter's declared tier something downstream of it. That turned a
field which had cost nothing into a bill: an agent routes at the **highest**
tier of the charters it holds, so a generalist holding one expensive charter
runs *all* its work on that model. **Twenty-five charters at the launch
roster.**

M11 already had the machinery — declared triggers, preregistered predictions,
measured effects. What it lacked was a metric, and its own docstring says adding
one is how the company becomes able to make a new kind of prediction about
itself. This is the two halves joined.

- `overtiered_charters` — exactly derivable from coverage and the charter
  registry, so it is checkable rather than trusted. `NONE` is excluded: that
  tier calls no model at all.
- `TriggerKind.TIER_WASTE` — fires at three, proposes fission, and the subject
  is scanned for rather than named.
- `orgdev/retiering.py` — propose, lock, Board, apply, onboard, measure.

```
1. AUDIT   moved 5   company 25 -> 21
2. RISK    moved 4             21 -> 17
3. INTEL   moved 3             17 -> 14
4. TRADE   moved 3             14 -> 11
5. KNOW    moved 3             11 ->  8
6. INFRA   moved 3              8 ->  5

agents 17 -> 23,  the trigger no longer fires
```

**The company reorganised itself six times on its own evidence and stopped when
its own rule said to.** It does not reach zero: five charters remain overtiered,
held by agents below the threshold of three. That is the declared rule working,
because two is a pair and a company that reorganised over a pair would never
stop.

### What it refuses to claim

The first split predicted −5 and got −5 — and **the company improved by 4**. The
new agent routes at `mid` and holds a `low` charter, so one of the five it
received is still above its written tier. Both numbers are on the report,
because one showing only the subject's would be claiming a fix it did not make.

And no money saved is printed. Every call here reports zero marginal cost under
a subscription, so no saving has been *observed*. The rate table is quoted —
`high` input is 15 per Mtok against 3 at `mid` — as what the gap is worth on the
metered path, labelled as such.

See [ADR-0020](adr/0020-the-company-pays-for-its-own-shape.md).

---

## M20 — The company asks, rather than being switched on ✅

The obvious last milestone was a live broker adapter. That is the wrong shape,
and the person who would have to fund it said so: he wants the agents, when
they are ready, *to tell him themselves* that they have a strategy worth trying
and that he should buy a live account.

Building an adapter and switching it on makes the human decide readiness on the
company's behalf. So M20 is a **standard**, an **assessment**, and an **ask**.

- `mandate/standard.py` — ten conditions declared in advance and hashed, each
  checked against a row the company already writes. No self-assessment.
- `mandate/assessment.py` — two verdicts, `ready` or `not_yet`. There is no
  third: a company that could report "nearly" would report it about everything.
- Only a `ready` escalates. A `not_yet` is recorded and nobody is interrupted.
- A database CHECK refuses `ready` while anything declared is unmet.

### The honest first answer

After running everything this company knows how to do:

```
BLOCKED  live_data           0 of 7 desks on live data; every one is a fixture
MET      authored            3 strategy designs authored by an agent
unmet    survived_selection  0 of 1 campaigns cleared the search; surplus -0.0267
MET      beat_the_baselines  1 of 3 attempts beat holding the asset
unmet    settled             authored claims: {'underpowered': 3}
BLOCKED  replicated          no replication has ever been recorded
MET      reviewed            1 objection raised: 1 upheld
unmet    risk_cleared        0 risk assessments
unmet    paper_gap_measured  paper trading never compared against a backtest
MET      chain_intact        chain verified: 306 events

NOT YET — 4 of 10. Nobody was interrupted.
```

### Blocked is not the same as unmet

*Unmet* is a research result: go and do better. **Blocked** means no amount of
research would help, because the machinery to produce the evidence does not
exist. Two conditions are blocked — no desk has a wired feed, and nothing
writes a replication record. That turns the standard from a scoreboard into the
company's own answer to *what to build next*.

### Running it found a bug in it

The first `reviewed` check required no upheld objection anywhere. A fully
exercised company fails that, because the M5 review ends with a critic correctly
killing a biased claim — so the criterion read unmet **because the critic had
worked**. A bar a healthy company can never clear is not a bar. And fixing it
between two assessments made the next report print, in red, that the standard
had moved — the guard firing on its own author.

See [ADR-0021](adr/0021-the-company-asks-rather-than-being-switched-on.md).

---

## M21 — The two things the mandate said were blocked ✅

M20's standard reported two conditions as *blocked* — unsatisfiable by any
amount of research, because the machinery did not exist. This is the company
acting on its own answer.

### Live data is a recording, not a connection

The hard part is not the HTTP call. **An experiment cannot be reproduced
against a moving endpoint**, and every preregistration here locks a spec whose
data fingerprint has to still mean something tomorrow. So a fetch is an event
with a record: vendor, endpoint, window, bar count, and a hash of every bar.
`SnapshotSource` then serves it through exactly the protocol the fixtures use —
the engine cannot tell the difference, and must not be able to.

```
SNP-0001   coinbase   BTC-USD   1h   3000 bars
           2026-05-06 to 2026-09-08
           digest c422d457...  verifies
```

**The company has seen a market.** It does not make the research powered: four
months of hourly bars against the fifteen years `desks/power` says the claim
needs.

### A replication must vary something

The `replications` table had existed since M5 with a docstring explaining what
it was for, and nothing had ever written a row into it. Every engine here is
deterministic, so a re-run returns the same number and learning that teaches
nothing — `Variation` is closed (`SEED`, `SHORTER_WINDOW`, `EARLIER_WINDOW`),
`vary()` never touches the rule, and the criteria are inherited from the lock.
That is why it costs no error budget.

### Two bugs the first runs found

**Same verdict is not the same as a result surviving.** Three variations of an
underpowered registration all came back underpowered and every one was recorded
as `held` — which `memory/confidence.py` counts as evidence, so replications of
nothing would have accumulated into confidence about nothing.
`NOTHING_TO_REPLICATE` now exists and is checked first.

**The pagination loop could not stop.** It terminated only on an empty page, so
a vendor returning overlapping data walked `end` backwards past the epoch until
`fromtimestamp` raised. The condition is now *progress*, with a floor behind it.

### A result can replicate and still be wrong

The first genuine `HELD` in the system is M5's registration under a seed
variation — the *survivorship-biased* rotation claim that the M5 review then
killed on an upheld objection. Replication tests whether a number survives a
perturbation, not whether the specification that produced it was honest, and
both records now sit against the same registration.

Nothing is blocked any more: every remaining condition is a research result
rather than a missing capability.

See [ADR-0022](adr/0022-live-data-is-a-recording-and-a-replication-must-vary.md).

---

## M22 — The paper cycle gets a driver, and the gates get read ✅

M20 said `risk_cleared` and `paper_gap_measured` had working machinery and no
command to drive it. Building the command showed that framing was wrong.
Nothing was missing a switch: a version reaches a paper book only through the
promotion gates, and **the seven gates had criteria since M8 whose observables
had never been fetched from anywhere.** Every test that promoted a version
typed the numbers in by hand.

### A gate is a reader

`aurelis trading readiness` fetches seven observables out of the company's own
record — a deflated Sharpe from the attempt and the family's trial count, an
excess over `always_long`, correlation against the book, objections against the
version's chain, replications that held, sealed queries released, and capacity
from a snapshot's own median bar volume.

Every reader either finds its number or returns **silence with a sentence
saying what is absent**. A silence is not a zero, and the difference runs in
exactly the direction that matters: a default of zero promotes strategies.

```
A  deflated_sharpe                     gte 0.95   0.0           FAIL
B  excess_sharpe_over_benchmark        gt 0       -0.00773818   FAIL
C  max_correlation_with_deployed       lt 0.5     0             PASS
D  open_critical_objections            eq 0       —             SILENT
E  surviving_replications              gte 1      0             FAIL
F  sealed_queries_used                 lte 1      —             SILENT
G  capacity_over_intended_allocation   gte 1      5.2362        PASS
```

Gate G is real data doing work: a median BTC-USD hour traded about 13.1m, one
per cent of which is five times the 25,000 the sleeve intended.

### Paper trades bars the research never read

A walk over the window the backtest ran on is the backtest again, paying
different fees. So `strategy author --snapshot` measures on a snapshot's early
window, 30% is reserved, and the walk starts where the research stopped. The
rule that trades is checked against the digest the attempt recorded; the claim
and the book must be on the same data; and the equity curve is rebuilt from the
fills after the walk rather than accumulated during it.

### Two conditions did not move, and that is the answer

`risk_cleared` and `paper_gap_measured` are downstream of promotion. A command
that produced a risk assessment for a version the gates rejected would be
manufacturing exactly the evidence the mandate asks for. What changed is that
the operator can now see *why*, computed gate by gate, instead of reading
"0 risk assessments".

### What the first walk actually said

The walk itself needs a version the gates cleared, which none of these have.
Forced past them once, on the same snapshot, purely to check the driver end to
end:

```
900 bars of SNP-0001 walked from bar 2100; the rule wanted
something on 44 of them, 44 orders filled, 0 refused

metric         backtest      paper        gap
total_return   -0.12340197   0.03209137   +0.15549334   held
sharpe         -0.03269854   0.01264270   +0.04534124   held
max_drawdown    0.16812606   0.11165526   -0.05647080   held
n_trades       52            44
turnover        0.02476190   0.04888889   +0.02412699
cost_drag       0.09872439   0.09502559   -0.00369880   held
```

**None of that is the strategy being good.** The held-out window is a different
stretch of market from the one the backtest read, so the gap mixes how wrong
the claim was with how different the two periods were. Telling those apart
takes many deployments, which is exactly why the mean gap is tracked as a
company competence rather than read off one run — and the command says so under
the table.

### Seven bugs the first runs found

**The driver was running a different strategy.** The first walk traded on all
275 bars where the backtest traded 52 times in 2,100. The intent compared the
target notional against the position's *market value*, which drifts with the
price every bar, so a rule holding one position for a week rebalanced seven
times. An intent now fires when the rule changes its mind.

**The report was lying about its data.** `caveat_for` hard-coded "the data is a
fixture rather than a market", so the first run against 3,000 hours of BTC-USD
printed a false caveat. Same defect as M18's, same sentence, found the same way.

**An approval is a ceiling and the size rounded half-even.** `PaperCycle` sized
orders with `quantize`'s default, which rounds *up* about half the time — and a
notional a hundred-millionth over the approval is refused outright.

**`cost_drag` was comparing two different quantities.** The paper figure
counted only the explicit broker fee while the engine charges its whole cost
model — fees, spread and slippage — so paper looked half as expensive as the
backtest assumed (0.042 against 0.099). Charging the slippage as well puts them
within four thousandths of each other, which is a finding rather than an
artefact: the cost model was about right.

**Deploying twice walked the strategy backwards.** The second `deploy` tried
to move a paper-trading strategy to `candidate`, which the state machine refuses
— correctly, and with a traceback at whoever typed the command twice. A version
already allocated is now reported as already allocated, kept apart from
"deployed" so a re-run cannot read as a decision.

**A refused deployment left the strategy stranded.** `deploy` walked the
strategy up its own state machine *before* asking for the promotion, so a
refusal left it at `under_review` and the next attempt crashed trying to walk it
back to `candidate`. Found by CI on the first run, because martex-quant is a
local wheel CI cannot install and gate A is therefore silent there. Now nothing
is written until nothing can refuse.

**A sourced engine claimed the wrong desk.** `LocalEngine(source=...)` defaults
its desk to `synthetic`, so the first snapshot-backed run was refused as "local
does not cover the crypto desk".

See [ADR-0023](adr/0023-a-gate-is-a-reader-and-paper-trades-what-research-never-saw.md).

---

## M23 — The company runs on a real model, and the seat had the answer key ✅

The first instruction to actually *run* the thing: a Claude subscription, real
models in the seats, real market data. It worked, and then it found something
much worse than a bug.

### What running it took

`aurelis model check --yes` made one real call through `agent_sdk` — Haiku,
6.4 seconds, zero marginal cost. `demo` and `agent hire` cost **4 model calls
between them**, because the deterministic work is done in software, which is
what §33 of the charter asks for. A five-attempt campaign costs about 20. The
whole pipeline is roughly 24 calls.

### The seat was reading the answer key

Raising `max_turns` past 1 to fix an unexplained provider failure did not fix
it — it revealed it. Streaming the raw SDK messages showed the agent answering a
design question by running `Grep` over this repository:

```
ToolUseBlock(name='Grep', pattern='one_day|three_days|six_hours|one_week')
ToolResultBlock(content='tests/test_campaign.py-199- ...')
ToolUseBlock(name='Grep', pattern='six_hours', path='src')
ToolResultBlock(content='src/aurelis/authoring/standin.py-41- ...')
TextBlock(text='ANSWER: three_days  BECAUSE: ...')
```

`allowed_tools=[]` reads as *no restriction*, not as *nothing allowed*. The
agent had read `standin.py` — the module that scripts what a stand-in is
supposed to answer — and the campaign tests, and then replied.

**None of the company's own honesty machinery could have caught it.** The figure
check passed, because every figure cited was real: it had gone and looked them
up. The preregistration passed, because the design was locked before the run.
The contamination lived in a subprocess the ledger never sees.

The guard is now a callback that denies every tool by name-independent refusal —
because after the built-ins were cut off, the next thing a seat reached for was
`mcp__claude_ai_Remote_Desktop_Commander__list_directory`, **an MCP server
belonging to the operator**. The reachable surface is not this repository's to
enumerate. See [ADR-0024](adr/0024-a-seat-has-no-tools.md).

### Four more bugs, all in what the agent was told

**The research window was capped at the fixture's size.** `SPAN_YEARS` is a
quarter because that is what the fixture holds, and `min(span, available)` threw
away real history: the first run against 40,000 recorded hours researched 2,190
of them. The recording decides the window now.

**The material told the agent its data was a fixture** while it was measuring a
recording of a real market — and the campaign's revision prompt did too, so a
revising agent was briefed differently from the attempt it was revising.

**The campaign's footer said "the data is a fixture rather than a market"**
under numbers measured on 28,000 hours of BTC-USD. The same class of falsehood
M18 found, in the sibling command.

**A lookback of "one hundred and sixty-eight bars" was refused as an invented
figure** when the model wrote `168`. The figure check compares numerals; the
choice spelled it in words. The material has to state a number in the form a
citation of it will take.

### What the agents actually produced

40,000 hourly BTC-USD bars, Feb 2022 to Sep 2026, hashed and verifying. 28,000
for research, 12,000 held back. Opus in the author's seat, five attempts, each
revising on the last one's result:

```
best observed        -0.0084199
expected best of 96   0.01503771
surplus              -0.02345763
survives the search   no
beat the baselines    no
```

Every design lost money. The best is below what a search of that width returns
from noise alone. The company reported: **the campaign found nothing.**

That is the system working. It ran on a real model, over a real market, and
concluded honestly that it had not found an edge.

---

## M24 — The company decides its own next action, and knows when to stop

`aurelis tick` has run the working day since M2. What it could not do is decide
what the day was *for* — every level above it was an operator typing the next
command. `aurelis run` is that decision, and almost all of it is about
stopping.

### The mandate is the work queue

No plan is carried in the loop. Each cycle it assesses its own standard, takes
the first action aimed at something unmet, and checks whether it moved. Every
action names exactly one condition; one that claimed several would keep looking
useful after the one it served was met.

### Repeating a search is not progress

The rule the layer exists for. A second campaign does not improve the odds of
the first — it widens the declared space, which raises the surplus the best
design must clear, faster than searching finds anything. **An unattended loop
that kept searching until something passed would be a machine for manufacturing
false discoveries, with the company's own preregistration machinery producing
the paperwork.**

So every action declares when it is exhausted, and returns a reason rather than
a boolean: *"we already did this and it did not work"* is the most important
sentence an autonomous loop can produce.

### What it did, on a real model, on a real market

```
1. campaign  acted  no change  CPN-0001: best -0.01146313, expected best of 96
                               is 0.01503796, surplus -0.02650109, survives: no
2. review    acted  MOVED      max_drawdown 0.12364208 -> 0.64507263 once 3
                               delisted name(s) are restored; confirmed -> refuted
3. replicate acted  no change  RPL-0001: seed -> nothing_to_replicate
4. —         stopped           every action that could move an unmet condition
                               is exhausted
```

18 model calls, under four minutes, nobody intervening. The review is the part
worth reading: the critic raised survivorship, the generated test ran, and a
**confirmed claim was refuted**. `reviewed` went MET and the mandate moved from
3 of 10 to 4.

Nothing else moved, and the loop named a reason for each: the campaign has run
and a second is not the answer; every replication found nothing to replicate;
no version has cleared its gates, and deployment refuses on evidence rather
than on anything a retry could change.

### Three bugs the first runs found

**It replicated five times and learned nothing five times.** Five different
registrations, each returning `nothing_to_replicate` because each original was
underpowered. By the letter not repetition — every registration was new. In
effect exactly repetition. The rule now reads the company's own record.

**A failed action was retried forever.** The exhaustion rules read persistent
state, and a failure usually leaves none: a refused authoring writes nothing at
all, on purpose, so the rule kept counting zero and the loop re-ran it every
cycle. Six identical failures, six times. An action that failed is now
exhausted for the run.

**Counting a table by name crashed the second cycle.** The rules counted
`campaigns`; the table is `authoring_campaigns`, and nothing checked the string.
They take mapped classes now, so the same mistake is an ImportError in the
suite rather than an OperationalError in an unattended run.

See [ADR-0025](adr/0025-the-mandate-is-the-work-queue-and-a-search-is-never-repeated.md).

---

## M25 — An agent picks its own market, states a view, and is scored on it ✅

Everything measured about an agent so far was a measurement of a rule it
chose from a menu somebody wrote in advance. This is the seat where the agent
is measured on its *judgement*, and the whole design follows from one
constraint: **a judgement cannot be backtested.** A model asked about last
year already knows what happened. So the evidence is forward, sealed before
the outcome exists, and scored when it does.

### The judgement seat

Two questions, two model calls, one row. *Which market?* — every instrument
the company holds a recording of, with a software-computed summary and the
agent's own record so far; nothing is assigned. *What do you think, and how
sure are you?* — a horizon from a closed set, a direction, a confidence, a
thesis in the agent's own words, and what would make it wrong. The prose is
figure-checked; the confidence is the one number the agent is allowed to
invent.

The row is hashed at sealing and the database refuses to change it, rescore
it or delete it. A horizon that already lies behind the clock is refused: the
one way a forward prediction quietly becomes a backward one is a stale
recording.

```
aurelis data fetch --symbol ETH-USD --yes     # a recording is what a view is sealed against
aurelis thesis seat --agent INTEL --agent QUANT
aurelis thesis list                           # open views with their horizon, scored ones with their score
aurelis thesis resolve --fetch --yes          # settle what a fresh recording covers
aurelis thesis calibration                    # Brier, hit rate, stated against observed by band
```

`calibrated` is the mandate's eleventh condition — thirty scored views on
market data with a mean Brier below the coin toss — and `judge` is the loop's
first action. It seats every judging agent on every recorded market and then
stops with the honest reason: what is missing is time and a fresh recording,
and the loop fetches nothing.

### What real agents did, on a real market

Three fresh Coinbase recordings (BTC-USD, ETH-USD, SOL-USD, 400 hours each,
last bar 2026-09-10 19:00Z). Seven agents on Sonnet, fourteen model calls.

```
INTEL    BTC-USD  down  72h  0.60   resolves 2026-09-13 19:00Z
LEAD-R   BTC-USD  down  24h  0.55   resolves 2026-09-11 19:00Z
QUANT    BTC-USD  down  24h  0.58
ENG-R    BTC-USD  down  24h  0.60
STRAT    BTC-USD  down  24h  0.56
CRITIC   ETH-USD  down  24h  0.56
VALID    declined
```

Six sealed, one abstention, zero refusals — every reply in the required form on
first contact, which no other seat here managed. One of them, in its own words:

> The tape is in a persistent multi-timeframe downtrend (-5.67% over 168 bars)
> and the post-drop rebound stalled at 77390.8 before grinding back down into
> 77134.22, a lower-high sequence that reads as distribution rather than
> accumulation.

**Six views, one opinion.** Every view says down. Seven agents with different
charters read the same twenty-four closes and reached the same conclusion in
different words. That is not a society disagreeing; it is one view written six
times, and the record will score it as six. Making the agents distinguishable
(their identity is now in the prompt) did not make them independent. That
needs different evidence — the event and entity layer the brief describes —
and an adversary whose job is to attack a view before it is sealed. Neither
exists yet.

**Half the falsifiers restate the proposition.** "Wrong if the close at the
horizon is above the reference" is the resolution rule. Nothing checks this
yet.

**Nothing is scored.** The forward record is empty until 2026-09-11 19:00Z,
and the station says so rather than showing a number.

### Five bugs the first runs found

**The cache handed one agent another agent's answer.** Identical material and
an identical system prompt is one cache key, correctly. The second agent seated
got the first one's view. The seat now carries the agent's handle, department
and charters, which is what makes the answer that agent's.

**The seal did not survive a round-trip.** `0.65` reads back as `0.65000000`
and `verify_seal` failed on every stored row. The seal is computed over the
stored form on both sides.

**Refusals were rolled back with the transaction that refused.** The event
recording an unreadable view was written inside the session that then raised.
It is appended in its own transaction now.

**The stand-in declined everything on the crypto fixture** because its market
regex did not allow the slash in `btc/usdt`. Found on the first offline run.

**A fixture recording anchored in January expired every horizon.** The fixture
feed lays its bars against the clock, marks the row as not a market, and the
mandate does not count it.

### What this milestone did not do

- **The 72-point design space is still in the tree.** The brief says delete
  it. It backs four mandate conditions and the paper driver, so removing it is
  the next milestone, not a side effect of this one.
- The material is twenty-four closes and four percentage changes. No events,
  no entities, no order books, no text.
- No agent attacks another's view. No position is taken on a view. Nothing
  is sized.
- Horizons are four fixed values; instruments are whatever has been recorded.

See [ADR-0026](adr/0026-a-judgement-is-sealed-before-the-outcome-exists.md).

---

## M26 — The menu is gone: a strategy is a rule the agent wrote ✅

The brief's one hard instruction about the existing code: delete the 72-point
design space, and do not replace it with a bigger menu. Done. What an agent
authors now is a **rule it wrote**, in a small closed language the engine runs
and the ledger hashes, through the same preregistration, selection correction
and gate machinery as before.

### The rule language

Clauses read top to bottom, each a condition over features of the closes up to
the current bar, each deciding long, short or flat. Eight features (`close`,
`ret`, `sma`, `ema`, `vol`, `high`, `low`, `rsi`), windows to 720 bars, at
most eight clauses, exact decimal arithmetic, no state, no loops, no I/O. It
parses to a canonical structure that hashes the same however it was typed; a
test changes the future and asserts the past does not move; the parser refuses
rather than guesses. The engine gained one signal kind, `rule`, rebuilt from
the registration's own payload so what runs is what was locked.

The author is shown the desk, its costs, the budget, prior work and the
language — never a measurement — and replies with the rule, a rationale and a
weakness in one call. The rule's numbers are the agent's; the rationale may
cite them and the material and nothing else. Two model calls per authoring
where the menu took six.

### One rule is one cell, and the correction had to get stricter

There is no enumerable space behind a written rule, so each rule is one
declared cell and a campaign's width is the number of rules it lets itself
write. That is a floor, stated as one: whatever a model weighed before writing
a rule down is uncounted, and the forward record (M25) is the check on that.

Shrinking the width from 96 to 4 exposed a weakness that had been there since
M16: `survives` was `surplus > 0`, and under the null the best of *n* draws
lands above its own expectation about half the time. **The first four-rule
campaign on a fixture survived.** A surplus must now clear the estimator's own
standard error, one-sided at 95%, and the fixture campaign no longer does.

### What a real model wrote, on 28,000 recorded BTC hours

Sonnet, in the author's seat, standalone:

```
(close > sma(720) and close > sma(168)) -> long
(close < sma(720) and close < sma(168)) -> short

total_return  -0.92667759      hold  +1.52260758
n_trades      1339             cost_drag  0.92620736
```

Its stated weakness was whipsaw in a range-bound regime, which is what
happened: 1,339 round trips at 40 bps ate 93% of the sleeve. Then a campaign of
three rules, each revised on the last one's result:

```
1  close < (low(168) * 1.01) -> flat | (close > (high(336) * 0.99) and close > sma(720)) -> long | ...
   sharpe 0.00182321   total return  0.00939685
2  close > sma(720) -> long | close < (sma(720) * 0.95) -> flat | else -> long
   sharpe 0.00058198   total return -0.18800562
3  ema(168) > (ema(720) * 1.01) -> long | ema(168) < (ema(720) * 0.98) -> flat | else -> long
   sharpe 0.00790851   total return  0.98572211

best observed          0.00790851
expected best of 3     0.00509665
surplus                0.00281186
margin it must clear   0.00983108
survives the search    no
beat the baselines     no
```

Three rules the menu could not have expressed — a breakout with a floor, a
trend gate with a stop band, an EMA ratio with hysteresis — and the third
returned +99% against +152% for holding the asset, with a surplus over the
search that is inside the estimator's noise. **The company reported that the
campaign found nothing.** That is the seat working: the agent could write
something new, and the measurement said what it was worth.

### What this milestone did not do

- The rule sees one instrument's closes. No volume, no cross-section, no
  events, no entities: the mechanical-rule half of the two evidence regimes,
  and not the scheme half.
- No critic reads a rule before it is measured; no filter, sizing or exit
  beyond the position the rule states.
- The M25 CI acceptance check was wrong for a scaled company and is fixed
  here: it counted views across two runs where it should have read the loop's
  own exhaustion reason.

See [ADR-0027](adr/0027-a-strategy-is-a-rule-the-agent-wrote.md).

---

## M27 — The company runs for days, and records what broke ✅

M25 made the evidence forward and M26 made the strategy the agent's own. Both
accumulate only if something records the market after a horizon passes and
seats the judges again — and until now that something was a person typing two
commands. This is the service that does the working day on its own.

### A person grants, once, on the record

`aurelis service grant` records which vendor and which instruments the
service may fetch: who, when, why, on the ledger, frozen by three triggers
(nothing but a revocation may change, a revocation is written once, nothing
is deleted). The autonomy loop still does not fetch; the service fetches only
under an active grant, and a test reads the source to assert nothing under
`aurelis/service/` can grant itself one.

### A wake is four steps, and none of them stops the next

Fetch under the grants. Settle every view a recording now covers. Run the
loop inside what is left of a rolling daily model-call budget. Write one row
per wake, whatever happened. A vendor that is down is a warning alert raised
by the Operations Director and the wake continues; a model out of allowance
is a failed action on the loop's record and the next wake retries.

```
aurelis service grant --source coinbase --instrument BTC-USD --instrument ETH-USD \
    --reason "the forward record needs fresh recordings every wake" --by <you> --yes
aurelis service start --every 1h --for 7d --calls-per-day 200
aurelis service status
```

### What two real wakes did

A grant for BTC-USD, ETH-USD and SOL-USD, recorded by the operator. The first
wake fetched all three, settled nothing (no horizon had passed), and seated
the judges on the fresh recordings: INTEL sealed a 72-hour view on SOL-USD,
then LEAD-R cited a rounded figure and was refused — and **the loop marked the
whole judge action failed and stopped seating the other five.** A refusal is
one agent's unusable reply, not a failure of the action; it is now recorded
as `refused`, the next cycle seats the next agent, and an agent whose last
word on the standing recordings was a refusal or a decline is not asked again
until a newer recording exists, because the same material gets the same
cached answer.

The second wake, with the fix, went through all seven:

```
INTEL    declined
LEAD-R   refused   cited 101, 101 -- rounded from a close near 100.09
QUANT    refused   cited 101, -102
ENG-R    declined
STRAT    sealed    SOL-USD down over 24h at 0.55
CRITIC   declined
VALID    declined
                   12 model calls, 184 left today, 0 incidents
```

Eight views now stand on the live workspace, every one of them *down*. The
first five resolve on 2026-09-11 at 19:00Z; a running service settles them on
its next wake.

### What this milestone did not do

- The service wakes on a clock only — not on a market event, not on another
  agent's finding.
- Four of seven judges declined on the second wake and two were refused for
  rounding. The seat's figure rule is doing its job and it is expensive; a
  material that shows fewer decimals would be refused less and would be a
  different question.
- Nothing has been scored yet. That is the point of the service, and it is
  the one thing this milestone cannot demonstrate in the hour it took.

See [ADR-0028](adr/0028-the-service-wakes-under-a-grant-and-records-what-broke.md).

---

## M28 — A view is attacked before it is sealed, and the attacker is scored ✅

M25's first seven views on a real model all said *down*. Seven agents read
the same closes and wrote the same conclusion in different words; putting
their identity in the prompt made them distinguishable and not independent.
A thesis nobody attacked has not been tested.

### The adversary in the loop

After the author's view is parsed, figure-checked and found forward, and
before anything is written, an agent holding the critic or adversarial
charter — never the author — is shown the same material and the proposed view
and replies with a verdict (`stands`, `weakened`, `broken`) and the strongest
reason the view is wrong. The author sees the attack and replies `hold`,
`revise` with a new confidence, or `withdraw`. All of it is sealed together
and covered by the immutability trigger; a withdrawal is a decline on the
ledger carrying the attack; the Brier score is computed on the confidence
*after*. An unreadable attack does not block the seal — it is recorded
against the critic and the view stands as stated.

### The critic is scored

When the horizon expires: `broken` on a wrong view is a catch, `broken` on a
right view is a false alarm, `stands` on a wrong view is a miss. Precision and
catch rate sit on the critic's agent page beside the author's calibration. Say
`broken` to everything and the false alarms say what that is worth.

### A real attack on a real view

STRAT, on the live workspace, proposed ETH-USD *down* over 6 hours at 0.55,
on a bounce off a flush low that had "already stalled twice near 2467.51".
CRITIC's verdict: **weakened**.

> The "stalled twice" claim rests on 2465.59 and 2467.51 — a gap no larger
> than ordinary hourly chop elsewhere in the series (e.g. 2477.41 to 2481.28,
> or 2472.22 to 2467.92), so calling it a defended supply zone reads noise as
> structure. Meanwhile the bars since the flush low of 2413.9 trace a steady
> grind of higher levels rather than a clean rejection, and the 6-bar change
> is +0.85%, i.e. the freshest momentum contradicts the fade thesis.

STRAT's response: **revise** to 0.52.

> The attack is right that two touches near 2465.59 and 2467.51 do not
> establish a defended supply zone and that the bars off 2413.9 grind higher
> rather than reject, so my structural claim was thinner than stated. What
> survives is only the weak prior that a fast retrace inside a mildly negative
> multi-day drift gives back part of the move, which leaves this barely
> distinguishable from a toss.

Every figure in both is in the material; the seal covers both; the view
resolves at 02:00Z. Whether the critic was right is on the record from then.

### A migration, found the same way

`create_all` creates tables that do not exist and leaves existing ones alone,
so the live workspace crashed on the first query that named an attack column.
Missing nullable columns are now added on init, the fact goes on the ledger
as `schema.migrated`, and the judgement triggers are dropped and recreated so
they cover the new columns rather than kept from before them.

### What this milestone did not do

- The attack reads the same twenty-four closes the author did. It can attack
  the reasoning, not the evidence.
- Nothing yet gives more budget to a critic with a good record or retires one
  with a bad one; the record that would justify it starts here.
- Four model calls per view where there were two.

See [ADR-0029](adr/0029-a-view-is-attacked-before-it-is-sealed.md).

---

## M29 — The world is entities, events and relations ✅

The deepest change in the brief, and the easiest to miss: the company's
entire ontology was a price series. The schemes it is supposed to find are
patterns over entities, events and relations inside time windows, and nothing
that shape could be represented, stored, mined or tested. Now it can.

### The layer

Entities with a kind, a key, attributes and a source. Events, typed,
timestamped twice (happened, learned), about one entity, hashed over what
happened so the same fact learned twice is one row — immutable by trigger.
Relations as typed edges, append-only. Queries: the events for an entity
since a moment, events of a kind between two moments, and the co-occurrence
of two kinds on the same entity inside a window.

Price is one event type among many. The bars stay in their recordings; what
enters the stream is derived from them deterministically with the recording
as the source — a volume spike at three times the prior 168-bar median, a
range break above the prior high or below the prior low.

### The first non-price source

The venue's own product catalogue, public and unauthenticated. Read on every
wake and diffed against what the company holds, it is a stream of the events
two of the brief's named mechanisms need: a product seen for the first time,
a status change, a halt, a disappearance.

```
aurelis world sync --yes          # the catalogue, once
aurelis world derive              # notable-price events from the newest recording
aurelis world events --entity BTC-USD
aurelis world cooccur --first price.volume_spike --second price.range_break --hours 24
```

The judges now see the recent events for the instrument they chose — the
first material a judge has been shown that is not a close.

### On the live workspace

```
837 product(s); 837 new, 0 status change(s), 0 gone
SNP-0002: 32 new event(s)   SNP-0003: 22   SNP-0004: 6
price.volume_spike then price.range_break within 24h: 37 pair(s)
```

Every product on the venue is an entity with its status — several already
`delisted` — and its base and quote assets as relations. Thirty-seven pairs
of a spike followed by a break on BTC-USD inside a day. **Every one is a
conjunction and none is a scheme.** The command says so under the table: a
mined pattern becomes a discovery only when an agent states a mechanism that
predicts something else, and that is tested separately. That machinery is
the next thing to build; the data it needs is now here.

### What this milestone did not do

- Nothing off-venue is in the stream: no social posts, no on-chain flows, no
  filings. Each is an adapter, a grant and a recording discipline of its own.
- No agent mines the stream or states a mechanism over it yet.
- A co-occurrence query is O(events) and in Python. Fine at thousands, not at
  millions.

See [ADR-0030](adr/0030-the-world-is-entities-events-and-relations.md).

---

## M30 — A mechanism is the join from a conjunction to a tested scheme ✅

The brief's critical design point. M29 can mine the event stream for
co-occurrences; M25 can score a forward view. Neither is a discovery. A mined
pattern becomes one only when an agent states a **mechanism** — why it works,
who is on the other side, how it decays — and that mechanism generates
**additional predictions** beyond the one it was found on, tested separately.

### The seat and the loop

An agent is shown a mined co-occurrence and states a mechanism, or declines.
The count is not a reason; a causal story and a decay model are required, and
the prose is figure-checked. The mechanism is hashed and immutable. It then
predicts every future occurrence of its trigger, each sealed before the
outcome and scored through the M25 resolver, tagged to the mechanism, the
training instance excluded. A mechanism whose out-of-sample predictions beat a
coin toss and the base rate is a candidate scheme; one that gathers evidence
and fails is retired and kept.

```
aurelis mechanism discover --trigger price.volume_spike --then price.range_break
aurelis mechanism list        # what each mechanism's out-of-sample record says
aurelis mechanism sweep       # retire mechanisms that failed with enough evidence
```

### What two real models did

Shown the spike-then-break co-occurrence on the live workspace — the one that
fired 37 times on BTC-USD — a Strategy agent and a Quant agent on Sonnet both
**declined to state a mechanism.** That is the design working: the seat did
not let a pattern become a scheme because it occurred often, and the model,
asked for a causal reason and who is on the other side, would not fabricate
one. Requiring a mechanism separated a coincidence from a scheme.

Offline, a stand-in states a deliberately-unfounded mechanism, its predictions
seal and score as the clock advances, they fail to beat the base rate of a
market that only rises, and the sweep retires it — the whole loop, at no cost.

### Also

An untracked, incomplete parallel draft (`aurelis/schemes/`) referencing
enum values that never existed was removed; it broke the type check and was
wired into nothing. The tracked implementation is `aurelis/mechanism/`.

### What this milestone did not do

- The trigger is a price-derived event, because that is what the stream holds;
  the social and on-chain sources the memecoin example needs are not built.
- No agent mines the stream to choose which conjunction to bring to the seat.
- A mechanism that becomes a scheme is not turned into a sized strategy; it
  accrues a record, and that is where this stops.

See [ADR-0031](adr/0031-a-mechanism-is-the-join-from-a-conjunction-to-a-scheme.md).

---

## M31 — The company hunts for mechanisms, and a scheme trades on paper ✅

Three gaps stood between M30 and agents developing their own strategies: an
operator named the pattern to bring to the seat, the trigger vocabulary was
two price events, and a mechanism that earned a record never became a
position. Closing the third found a flaw in M30's own bar.

### The base rate was wrong, and a perfect mechanism could not pass it

M30 measured a mechanism against the up-frequency among its own predictions.
That is conditioned on the trigger — it is the signal — so a mechanism right
every time had a base-rate Brier of zero and read as worse than the base
rate. The bar is now the instrument's **unconditional** drift over the same
horizon: what a forecaster who knew only how often the market went up would
have scored. A test builds a market whose drift is a coin toss and whose
post-spike six hours always rise; the mechanism is a scheme.

### The company hunts

`aurelis mechanism mine` ranks every ordered pair of event kinds that
co-occurs inside a window. The loop's `discover` action brings one (agent,
pair) to the discovery seat per cycle — one active mechanism per trigger,
every pair to every judging agent, then it stops — after `judge`, so the
forward record is never starved. Four more derived events (momentum flip,
volatility squeeze and expansion, drawdown) give the agents more to reason
about. The mandate has a twelfth condition, `scheme`.

### A scheme trades on paper, through the same chain as anything else

Only a candidate scheme trades. It is composed into a strategy version by the
Strategy Architect — the write-scope guard refused the researcher who stated
it, which is the org design working — given five percent of the paper book,
and every firing goes through Risk, approval, execution and post-trade.
Opens at the reference close, closes at the resolution close, realised P&L
after fees on the record. Reported, never judged.

```
aurelis mechanism mine          # ranked conjunctions; a list, not a discovery
aurelis run                     # judges, then brings every pair to every agent
aurelis mechanism trades        # what each scheme did on paper
```

### On the live workspace

```
price.volume_spike  then price.volume_spike   108 on 3 instruments
price.volume_spike  then price.range_break     53 on 3
price.range_break   then price.range_break     40 on 3
price.range_break   then price.volume_spike    30 on 3
```

The first forward view scored: STRAT's six-hour ETH short, weakened by the
critic to 0.52, was right — Brier 0.2304 over one, twenty more standing. The
service now runs the whole loop unattended, hourly, under the grant.

### What this milestone did not do

- Every trigger is still price-derived. The memecoin example needs social and
  on-chain sources that do not exist.
- A scheme's share of the book is a constant, not a function of its record.
- Nothing closes a paper position early on a kill latch.

See [ADR-0032](adr/0032-the-company-hunts-and-a-scheme-trades-on-paper.md).

---

## M32 — The book and the tape enter the event stream ✅

Through M31 every agent and every mechanism reasoned over closes and events
derived from closes. The venue the company records already serves, without
credentials, the top fifty levels of its order book and the most recent
trades with the side that took liquidity. Now it is read.

### Two readings per instrument per wake

`book.snapshot`: mid, spread in basis points, depth within one percent of the
mid on each side, and the bid share. `flow.trades`: taker buy and sell volume
over the most recent trades, the buy share, the volume-weighted price. When
either is lopsided past sixty-five percent, a derived kind fires too —
`book.bid_heavy` / `book.ask_heavy`, `flow.buy_pressure` /
`flow.sell_pressure` — so a mechanism can fire on it and mining can join it
to a move. The raw payloads are one artifact whose digest the events carry.

**The trade's side is the maker's.** A `buy` row is a resting buy a seller
hit; the aggressor sold. Read naively it inverts every flow signal while
looking exactly like one. The inversion lives in one function and a test
pins it.

### On the live workspace, the first readings

```
BTC-USD  mid 77242.10  spread 0.0013 bps  bids 16,008,176  asks 14,968,889  bid share 0.5168
         500 trades    taker bought 1.6522  sold 1.1831    buy share 0.5827   vwap 77250.82
ETH-USD  mid 2466.00   spread 0.4461 bps   bids  6,597,965  asks  6,756,717  bid share 0.4941
         500 trades    taker bought 99.04   sold 67.22     buy share 0.5957   vwap 2466.14
SOL-USD  mid 99.74     spread 2.0052 bps   bids  4,072,341  asks  4,273,426  bid share 0.4880
         500 trades    taker bought 394.09  sold 367.56    buy share 0.5174   vwap 99.72
```

Nothing lopsided past the threshold, so no heavy event — which is the
reading, not a gap. The service now takes these every wake under the grant,
the judges see the newest of each kind first, and a test states a mechanism
on `flow.buy_pressure` and watches it seal a forward prediction.

### What this milestone did not do

- One venue's book and tape. Funding, basis, open interest, options,
  on-chain, social, filings: each an adapter under the same discipline, none
  built.
- Hourly readings are slow for microstructure; nothing wakes on an event.

See [ADR-0033](adr/0033-the-book-and-the-tape-enter-the-stream.md).

---

## M33 — The miner shows its evidence, and a decline says why ✅

Five real agents had declined to state a mechanism over a mined pair, and
the seat had shown them a count. A count is not a reason, and it is also not
enough to reason from.

### The evidence, labelled as in sample

For the trigger at 6, 24 and 72 hours: occurrences a recording could settle,
the mean return after them, the share that rose — and the same figures after
*any* bar, on the same recordings. The note under the table says what it is:
the reason to ask, computed on the data the pattern was mined from, not
evidence it predicts anything; the out-of-sample predictions are the test.
The evidence shown is an artifact the mechanism names. A decline may now
carry `BECAUSE:`, recorded on the ledger.

### What the live evidence said, and what happened

```
after price.volume_spike   6h: n 38, up 0.5526 | any bar up 0.5093
                          24h: n 32, mean -1.18%, up 0.3125 | any bar up 0.5098
after price.range_break    6h: n 16, mean +0.58%, up 0.9375 | any bar up 0.5093
                          72h: n 13, mean +2.50%, up 0.8462 | any bar up 0.5144
```

The agents that declined an "up" mechanism on the spike were right: six
hours on it is a coin toss and a day on it the price fell two times in three.
Shown the range-break figures, three real agents still declined — sixteen is
thin — and a fourth, the Validation agent, stated the company's first
mechanism:

> **MEC-0001 — Breakout stop-cascade momentum continuation.** A range break
> in a heavily-leveraged, thin-order-book asset trips clustered stop-loss and
> liquidation orders on the side caught wrong, and that forced flow plus
> trend-following systems chasing the break push price further before the
> move exhausts. Up over 6h at 0.68. Other side: leveraged traders and market
> makers positioned against the break, and fade traders forced to cover.
> Decay: a well-known, widely-traded effect; as capital crowds into
> anticipating it the cascade gets front-run and the edge should compress
> over weeks to a few months, faster on the more liquid instrument.

It has zero predictions, correctly: every past break's horizon has elapsed.
Its first sealed prediction comes with the next break the service derives,
and it has to beat the instrument's own drift out of sample as if nobody had
believed it.

See [ADR-0034](adr/0034-the-miner-shows-its-evidence.md).

---

## M34 — A mechanism is tested across the universe, not on one chart ✅

`MEC-0001` needs twenty out-of-sample predictions and the live grant named
three instruments, so it could fire about once a day. Prediction generation
never cared which chart a mechanism was found on — it seals on every
occurrence of the trigger kind, on whatever instrument — so the typed list of
three was the only throttle on the company's evidence.

### A grant drawn from the venue's own ranking

`aurelis service grant --universe USD --top 30` reads the vendor's one-call
stats document, ranks USD-quoted instruments by **dollar notional** (by units
PEPE, MOG and BONK are the top three; by dollars none is in the top twenty),
sets aside any instrument whose 24-hour range was under 0.2% as pegged — the
measurement, not a list of stablecoin names — and grants the top thirty. The
rule in words and the ranking's artifact digest go on the grant and are
frozen with the instrument list; the service never re-runs the rule. `aurelis
service universe` shows the ranking and writes nothing. An instrument on two
grants is fetched once.

### Tested wherever the event fires

A test states a mechanism on one instrument, records a second, and the
mechanism seals on the second's range breaks — none marked as training — and
scores on the second's own recording.

### What the live workspace did meanwhile

The service's first wake on M33 code brought the spike-then-spike pair to
the agents with its in-sample evidence. Four declined, each with a reason,
and the reasons agree: a volume spike after a volume spike is volatility
clustering, a variance mechanism with no side to it. A fifth, the Research
agent AG-0004, read the same table the other way — the 24-hour figure said
the price *fell* two times in three — and stated **MEC-0002, leveraged
liquidation-cascade exhaustion reversal**: a spike is forced flow that runs
out of fuel, the momentum flip after it marks the point the marginal buyer is
gone, and price bleeds lower over the day as the unwind continues. Down over
24h at 0.55; the other side is late leveraged longs buying the spike as a
breakout. Eleven forward predictions sealed within the hour. Two mechanisms,
both gathering, both against the instrument's own drift; the universe grant
is what lets them be judged in days rather than months.

See [ADR-0035](adr/0035-a-mechanism-is-tested-across-the-universe.md).

---

## M35 — The leverage the agents keep citing enters the stream ✅

Both live mechanisms are stories about liquidation cascades and crowded
leveraged longs, stated over closes, a book and a tape. The company held no
funding rate and no open interest. Now it does.

### Funding and open interest as events on the spot instrument

Under a `bybit` grant that names the same spot symbols as the universe grant
(`--from-grant GRT-0002`), every wake reads each instrument's USDT perpetual
without credentials: `leverage.funding`, one per eight-hour settlement with
the rate and its annualised figure; `leverage.open_interest`, one per hourly
reading with the change over a day. They are recorded on the spot instrument
so that mining joins them to price events and a mechanism on funding seals
against the spot close; the perpetual is its own entity, `derivative_of` the
spot. Derived: `funding.extreme_positive` / `_negative` past five basis
points a settlement, `oi.surge` / `oi.purge` past ten percent a day — each
carrying the threshold that fired. The same settlement read twice is one
event. A symbol with no perpetual is counted, not an incident.

### Tested

A mechanism stated on `funding.extreme_positive` seals a forward prediction
against the spot close at the settlement. The judge's material shows the
funding line and the open-interest line by the newest-per-kind rule.

### What the live workspace did

The first wake under the leverage grant read twenty-six perpetuals (four of
the thirty have none), recorded fifty-four leverage events and derived two
open-interest purges — ZEC's open interest had fallen fifteen percent in a
day. The same wake scored the first two mechanism predictions ever: MEC-0001
right on RAY-USD, MEC-0002 wrong on VTHO-USD. One each; nothing to conclude.

Reading the page afterwards found a display bug: the mechanisms table and
`mechanism list` printed the calibration's *own* base rate — conditioned on
the trigger, and with one scored prediction a perfect forecaster, `0.0000` —
where the unconditional figure retirement compares against belongs. Fixed,
with a test that only passes when the two differ.

See [ADR-0036](adr/0036-the-leverage-the-agents-cite-enters-the-stream.md).

---

## M36 — Mission Control shows the hunt ✅

The mechanism loop was the company's most important work and nobody could
watch it without opening the database.

### A page per mechanism

`/mechanism/<ref>`: the causal statement, what the agent was shown unfolded
from the evidence artifact with the in-sample figures labelled as such, the
record with the unconditional base rate, the tally by instrument, every
prediction with its outcome linked to its thesis, the paper trades, and the
other agents who were shown the same trigger and declined — with their
reasons. The mechanisms page gained "Declined, and why" under its table and
links every mechanism to its page. The page computes nothing: every figure is
the library's or the resolver's.

See [ADR-0037](adr/0037-mission-control-shows-the-hunt.md).

---

## M37 — The facility in pixels ✅

The brief's pixel-art research complex, under one rule: a pixel carries
identity, measured state, or nothing.

Every agent has a deterministic eight-by-eight avatar drawn from the hash of
its reference, lit by its state, worn on its page and on the mechanisms it
stated. A room's LED blinks and its staff sprites move only when the room is
working. A gathering mechanism shows a bar of `scored / 20` with the numbers
beside it. Crisp edges, floor tiles, a scanline shell, a blocky mark: all
generated, no assets, the sealed build still one file. The overlap check and
the no-placeholder tests hold.

See [ADR-0038](adr/0038-the-facility-in-pixels.md).

---

## M38 — A mechanism may fire on the conjunction it was shown ✅

Through M37 the miner showed an agent a pair and the mechanism it stated
fired on the trigger alone: shown "spike then spike within 24h", `MEC-0002`
predicts after any spike. The discovery form now carries `FIRES_ON: trigger |
conjunction`. On `conjunction` the mechanism records the second kind and the
window, and a prediction seals only when the second event follows the trigger
inside the window on the same instrument, at that instant, against the spot
close then. A second event that completes several pairs is one occurrence.
The evidence shows the effect after the trigger, after the conjunction and
after any bar side by side, so the agent can see where the follow-through is
before choosing. The conjunction fields enter the seal only when set; a test
recomputes the pre-M38 digest for a trigger mechanism and it matches.

The station and the CLI print what a mechanism fires on:
`price.range_break ⇒ price.range_break ≤48h`.

### What the live workspace did

The service died with the previous session at 11:08Z on the 11th and was
restarted on this tree at 05:05Z on the 12th. Its first wake scored the
backlog — 115 predictions — and the record moved:

- **MEC-0001 is a candidate scheme.** 26 scored out of sample, 25 right,
  Brier 0.1162 against the instruments' own drift at 0.2700. It opened two
  paper positions through Risk at the wake, five percent of the paper book
  each, and closes them at the horizon.
- **MEC-0002 is retired.** 79 scored, 29 right: a down call over 24 hours
  on a day the universe rose. Brier 0.2658 against 0.2323, and the sweep
  wrote why.

The caveat the record does not yet count: MEC-0001's twenty-six predictions
came from about eighteen hours across thirty instruments that move together.
Twenty-six sealed predictions are not twenty-six independent trials; on a
day when everything broke upward and kept going, they are closer to a few.
Counting evidence by independent episode rather than by prediction is the
next thing the library has to learn, and until it does "candidate scheme"
means exactly what M31 defined and no more.

See [ADR-0039](adr/0039-a-mechanism-may-fire-on-the-conjunction.md).

---

## Sequencing

```
M0 ─▶ M1 ─▶ M2 ─▶ M3 ─▶ M4 ─▶ M5 ─▶ M6 ─▶ M7 ─▶ M8 ─▶ M9
                    │            │                        │
                    │            └──▶ M10 ✅ ▶ M11 ✅ ────┤
                    │                                     │
                    └─────────────────────────────────────┴──▶ M12 ✅ M13 ✅
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
| M8–M10 | **17, actual** | CRYPTO |
| M11 | **19, actual** | CRYPTO |
| M12 | **19, actual** | **all 7, actual** |
| M13 | **47, actual** (154 proved) | **all 7, actual** |

The M8, M11 and M12 rows read ~22, ~28 and 45→80 when this was written. The
actual numbers are far lower and the difference is the point: **nothing hired
anybody.** No measured trigger fired for a strategy, risk or trading specialist
through M8 and M9, so the launch generalists kept standing in; M11 grew the
company by exactly the two agents its own trigger scan justified; and M12
opened all seven desks without hiring for any of them, because a desk running
on fixtures generates no load and the trigger table fires on load. A roadmap
that predicted headcount and a company that hires on evidence will disagree,
and the company is the one that is right.

M13 staffed the desks — through the same org-change lifecycle, on the measured
condition that seventy-eight jobs existed and nobody held them — and reached
47. Not 80: a desk running on fixtures generates no load, and each desk got one
generalist per department exactly as the launch roster staffed crypto. The
"100+" row is now proved rather than reached: a test hires into all **154**
slots and checks that coverage stays intact, authority still resolves and the
write-scope guards still refuse. The number in that column was always a claim
about the software.

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
