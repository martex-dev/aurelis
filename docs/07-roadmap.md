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
