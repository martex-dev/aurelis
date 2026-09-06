# 04 — Domain Model

Date: 2026-09-04
Status: proposal, v2.

Entities, lifecycles, and — the part that carries the weight — **who is
permitted to write what**.

---

## 1. Map

```
ORGANIZATION                 WORK                        RESEARCH
──────────────               ──────                      ────────
Department                   Mission                     MarketObservation
   └ Desk                       └ Project                Hypothesis
   └ Team                          └ Task                   └ Registration
      └ Agent ─── Role                                          └ Experiment
           └ Coverage                                              └ Run
           └ Skills                COMMUNICATION                      └ Result
           └ Permissions           ─────────────                         └ Artifact
           └ Metrics               Message                       Finding
      └ OrgChange                  Channel                       Evidence
                                   Meeting                       Objection
STRATEGY                              └ Turn                     Replication
────────                              └ Decision                 Critique
Strategy                              └ ActionItem
   └ StrategyVersion                                             KNOWLEDGE
   └ PromotionGate            TRADING                            ─────────
                              ───────                            KnowledgeNode
PORTFOLIO                     TradeProposal                      KnowledgeEdge
─────────                     RiskAssessment                     Lesson
Portfolio                     TradeApproval                      MemoryEntry
   └ Allocation               Order                              Alert
   └ ExposureSnapshot         Position                           AuditRecord
                              PostTradeReport                    Event (chained)
```

---

## 2. Organization entities

### Department

`department_id · name · charter · head_agent · roles[] · channels[] · metrics`

Static configuration, versioned in the repository. Departments are created by
humans, not by agents.

### Desk

```
Desk:
    desk_id          CRYPTO | EQUITIES | OPTIONS | FUTURES | COMMODITIES | FX | MEMECOIN
    instruments[] · calendar · trading_hours · data_sources[]
    engines[] · cost_model · liquidity_model
    risk_limits · constraints
    status           PROPOSED | OPENING | ACTIVE | DORMANT | CLOSED
    opened_at · closed_at · closure_reason
```

**Lifecycle:** a desk opens when it has data, an engine, staff and risk limits.
It goes `DORMANT` when nothing is studied there for a declared window, and
`CLOSED` with a recorded reason.

**Written by:** Board decision only.

### Role

```
Role:
    role_id · name · department · charter
    seniority_levels[] · default_tier
    required_competences[] · required_playbooks[]
    default_read_scope · default_write_scope · default_tool_scope
```

A closed registry of 76 charters (`docs/02-organization.md` §4). Adding a role
is a repository change with a test, not a runtime action — a role that can be
invented at runtime cannot have its permissions reviewed.

### Agent

```
Agent:
    agent_id · name · role · department · desk · team · seniority
    coverage[]              which charter areas this agent holds
    skills[] · playbooks[] · tools[] · channels[]
    read_scope · write_scope · tool_scope     (resolved)
    model_policy · daily_budget
    memory_scope
    metrics                 calibration · throughput · quality · cost
    state                   IDLE | WORKING | IN_MEETING | BLOCKED | SUSPENDED
    lifecycle               HIRED | ONBOARDING | ACTIVE | SENIOR | LEAD
                            | DIRECTOR | RETRAINING | SUSPENDED | RETIRED
    hired_at · onboarded_at · promoted_at · suspended_at · retired_at
    hired_by_org_change
```

**Lifecycle:** see `docs/02-organization.md` §10.

**Written by:** the runtime for `state`; the Org Development process (via a
meeting decision) for everything structural. **An agent cannot modify its own
record** — not its coverage, not its permissions, not its metrics.

### Team

`team_id · name · department · desk · lead_agent · members[] · charter ·
projects[] · metrics · status`

**Written by:** department head, ratified in a Board or department meeting.

### OrgChange

```
OrgChange:
    change_id · kind    HIRE | FISSION | FUSION | PROMOTE | SUSPEND | RETIRE
                        | OPEN_DESK | CLOSE_DESK | FORM_TEAM | DISSOLVE_TEAM
                        | GRANT_COMPETENCE | REVISE_PLAYBOOK
    proposed_by · trigger · trigger_evidence[]
    justification · predicted_effect · measurement_plan · measure_after
    decided_by_meeting · decision · decided_at
    applied_at · measured_effect · verdict
```

**The company's structure has a version history exactly like a strategy does.**
Every change predicts an effect and is measured against it afterwards,
including the ones that made nothing better.

**Written by:** Org Development Lead proposes; a meeting decides; the runtime
applies and later measures.

---

## 3. Work entities

### Mission

```
Mission:
    mission_id · objective · scope · rationale · priority
    owner_agent · departments[] · desks[] · teams[]
    constraints · deadline · budget · spent
    status · progress · outputs[] · decisions[]
    kickoff_meeting_id · retrospective_meeting_id
```

**Lifecycle:**
```
PROPOSED → PLANNING → ACTIVE → REVIEWING → CLOSED
                 ↓        ↓         ↓
             CANCELLED  PAUSED   BUDGET_EXHAUSTED
```

Two enforced transitions:
- `PLANNING → ACTIVE` requires `kickoff_meeting_id` to be set.
- `REVIEWING → CLOSED` requires `retrospective_meeting_id` to be set.

That is how "meet at the start and at the end" is a property of the system
rather than a habit.

`BUDGET_EXHAUSTED` is a legitimate terminal state, not an error. A company that
cannot afford to answer a question has learned something about the question.

**Written by:** Executive opens and closes; the runtime transitions on budget.

### Project

`project_id · mission_id · name · lead_agent · team · desk · hypotheses[] ·
deliverables[] · budget · status · kickoff_meeting_id · retro_meeting_id`

Same kickoff/retrospective rule at the project level.

### Task

```
Task:
    task_id · project_id · assignee_agent · created_by
    type      RESEARCH | ANALYSIS | EXPERIMENT | REVIEW | CRITIQUE
              | REPLICATION | BUILD | MONITOR | BRIEFING | DECISION
              | MEETING_ACTION
    subject · inputs · expected_artifact_kind
    allowance · priority · due_at
    status    QUEUED | CLAIMED | IN_PROGRESS | BLOCKED | DONE
              | FAILED | REFUSED_BUDGET | CANCELLED
    blockers[] · result_artifact · cost
```

Failed tasks are **recorded, never retried into success**. An agent that
cannot produce a valid artifact has told the company something about the agent
or the task, and burying that under retries erases the signal.

---

## 4. Communication entities

### Message

`message_id · from_agent · to[] · cc[] · channel · type · priority · subject ·
body · claims[] · evidence_refs[] · requires_response · respond_by · thread_id
· in_reply_to · read_by[]`

Types in `docs/01-architecture.md` §4.

### Channel

`channel_id · kind (DEPARTMENT|DESK|TEAM|MISSION|COMPANY) · name · members[] ·
retention · post_permissions`

Reading a channel an agent does not belong to is a permission error.

### Meeting

Full definition in `docs/03-meetings.md` §7.

```
Meeting:
    meeting_id · type · subject · trigger
    mission_id · project_id · department · desk
    chair · participants[] (role at the time) · observers[]
    agenda[] · evidence_pack[]
    turns[] · forecasts[] · forecast_scores[]
    objections[] · discriminating_tests[] · test_results[]
    decisions[] · dissent[] · action_items[]
    budget · tokens · cost · duration
    productive           ≥1 state change
    status   SCHEDULED | IN_SESSION | SYNTHESISING | CLOSED | ABANDONED
```

### Turn

`turn_id · meeting_id · round · phase · speaker · addressed_to[] · kind · body
· claims[] · evidence_refs[] · stance · changed_mind_from · tokens · cost`

**Written by:** agents, through the meeting runtime only. Turns are immutable
once recorded.

### Decision

`decision_id · meeting_id | agent_id · subject · outcome · rationale ·
supporting[] · dissenting[] (agent, reason, evidence) · action_items[] ·
decided_at · decided_by`

**Dissent is a stored field.** A decision that records no dissent is a decision
where nobody disagreed, which is different from a decision where disagreement
was smoothed away.

---

## 5. Research entities

### MarketObservation

```
MarketObservation:
    observation_id · desk · source · subject
    as_of                when it was true
    observed_at          when the company learned it
    payload · artifact_hash · reliability_score
    author_agent
```

**Bitemporal.** `as_of` and `observed_at` are separate columns because
collapsing them is how look-ahead enters through the data layer.

### Hypothesis

```
Hypothesis:
    hypothesis_id · project_id · desk · claim
    minimum_effect · expected_variability · rationale
    author_agent · parent_id · derivation_kind
    state · novelty_check · prior_art[]
```

**Lifecycle:**
```
DRAFT → SCREENED → REGISTERED → DESIGNED → RUNNING → ANALYZED
   ↓                                                     ↓
SHELVED                              CHALLENGED → REPLICATED → REVIEWED
                                                                 ↓
   terminal: CONFIRMED · REFUTED · INCONCLUSIVE · REVISED
             · ABANDONED_BUDGET · SHELVED
```

`REFUTED` and `INCONCLUSIVE` are terminal **successes** and are reported with
the same prominence as `CONFIRMED`. The graveyard is a first-class room in
Mission Control, not a tab.

`derivation_kind`: `ROOT · SPECIALISATION · GENERALISATION ·
REFUTATION_RESPONSE · MERGE · ABLATION · FOLLOW_UP_FROM_FAILURE` — so "what did
we learn from the failures?" is a query.

**Written by:** Researchers and Strategy Lab create. **State transitions are
written by the runtime, never by an agent.**

### Registration

```
Registration:
    registration_id · hypothesis_id
    spec · spec_hash · analysis_plan · seed_root
    kind          CONFIRMATORY | EXPLORATORY | REPLICATION
    declared_cells · family_id
    pass_criteria · fail_criteria      committed BEFORE the run
    locked_at · locked_by (Registrar)
```

**The most protected table in the system.** Three invariants:

- A `Run` cannot exist unless a locked `Registration` for it predates it.
- Once locked, `spec`, `spec_hash`, `analysis_plan`, `seed_root` and `kind`
  cannot change. A revised design is a **new row**, degraded to `EXPLORATORY`.
- No forecast may be recorded once any run exists for the registration.

All three are database triggers. Deciding what counts as success after seeing
results is not discouraged — it is impossible.

`declared_cells` is what the family **declared**, not what it ran: a grid of 20
features × 10 horizons costs 200 even if 50 ran. That closes the
declare-big-run-small loophole in multiple-testing accounting.

**Written by:** Registrar only.

### Experiment / Run / Result / Artifact

```
Experiment:   experiment_id · registration_id · engine · desk · spec
Run:          run_id · experiment_id · code_version · data_fingerprint · seed
              status (COMPLETED | INFRA_FAILURE | SCIENTIFIC_FAILURE
                      | TIMEOUT | OOM) · started_at · duration · resources
Result:       result_id · run_id · metric · value · confidence_interval
              split (TRAIN|DEV|SEALED) · computed_by (ENGINE|CUSTODIAN)
              artifact_hash
Artifact:     hash (PK) · kind · size · created_at · produced_by_run
```

Infrastructure failures may be retried. **Scientific failures never are** — they
become research objects in their own right.

`computed_by` accepts only `ENGINE` or `CUSTODIAN`. **No agent may write a
Result row.** Sealed-split metrics accept only `CUSTODIAN`.

### Finding / Evidence

```
Finding:   finding_id · hypothesis_id · statement · interpretation
           author_agent · confidence (COMPUTED) · confidence_cap_reason
           evidence[] · objections[] · replications[] · status
Evidence:  evidence_id · finding_id · kind · polarity (SUPPORTS|CONTRADICTS)
           artifact_hash | observation_id | source_id · verbatim_passage
```

Assertion ladder — promotion between levels is illegal:

| Kind | Requires |
|---|---|
| `OBSERVED_FACT` | Written only by engines or the Custodian, from artifacts |
| `SOURCED_CLAIM` | A resolvable source and a stored verbatim passage |
| `INFERRED_CLAIM` | At least one parent evidence row |
| `HYPOTHESIS` | Never evidence for anything |
| `SPECULATION` | Excluded from every report and every metric |

**Confidence is computed, never asserted**, from: replication count, effect
size over interval width, open critical objections, registration kind, sealed
queries consumed, and independent-support count from the knowledge graph.
`confidence_cap_reason` is carried so a contested finding still reads as
contested when it is recalled six months later.

### Objection

```
Objection:
    objection_id · target (finding|strategy|data|run) · author_agent
    type · severity (MINOR|MAJOR|CRITICAL) · statement
    discriminating_test_spec        an executable spec that would settle it
    status (OPEN | RESOLVED_UPHELD | RESOLVED_REJECTED | EXPIRED)
    resolution_run_id
```

Closed taxonomy, so objections can be scored against planted defects in
training scenarios:

*Research:* `LEAKAGE · CONTAMINATION · WEAK_BASELINE · CONFOUND ·
MULTIPLE_TESTING · SEED_INSTABILITY · METRIC_INVALID · UNDERPOWERED ·
IMPLEMENTATION_BUG · ALTERNATIVE_EXPLANATION · GENERALISATION_OVERREACH`

*Market:* `SURVIVORSHIP · LOOKAHEAD · COST_UNDERSTATED · LIQUIDITY_UNREALISTIC
· REGIME_SPECIFIC · CAPACITY_IGNORED · CROWDING · DATA_REVISION`

`CRITICAL` gates promotion while open. `EXPIRED` ages out into a *reported
unresolved limitation* rather than a permanent blocker.

### Replication

`replication_id · parent_registration_id · varied · outcome
(REPLICATED | PARTIALLY | FAILED | INCONCLUSIVE) · run_id · author_agent`

A replication **spends no error budget**; a stress test **can only demote** —
surviving one confers no significance.

---

## 6. Strategy entities

### Strategy / StrategyVersion

```
Component:        component_id · ref · kind (SIGNAL|FILTER|ENTRY|EXIT|SIZING)
                  name · spec · spec_digest · rationale
                  origin (INVENTED|DERIVED_FROM_FAILURE|ADAPTED|REFINED|COMBINED)
                  origin_ref · author · desk · assumes[]
Strategy:         strategy_id · ref · name · thesis · desk · state
                  current_version · owner_agent · created_at
                  retired_at · retirement_reason
StrategyVersion:  version_id · ref · strategy_ref · n · spec · spec_digest
                  desk · universe · cost_model · constraints · risk_assumptions
                  evidence[] · known_weaknesses[] · supersedes
                  material_change · created_by · promoted_at · promoted_by_meeting
VersionComponent: version_ref · component_ref · role · position · weight
StrategyLineage:  version_ref · act · parent_ref · detail · author · meeting_ref
StrategyPortab.:  version_ref · desk · status (NATIVE|UNPROVEN|PORTED
                                              |REFUTED_HERE|INAPPLICABLE)
                  reason · evidence_ref · assessed_at
```

**A strategy is composed, never promoted.** There is no `hypothesis_ref` here
and no function that creates one from a result
([ADR-0010](adr/0010-strategies-are-composed-not-promoted.md)). Agents author
`Component` pieces with a stated rationale and a cited, shape-checked origin,
and a version is what those pieces make. `Origin.DERIVED_FROM_FAILURE` is the
only bridge from research: a refuted hypothesis is *material*, not a candidate.

Counting origins gives a measured answer to "did the company create this?" —
a version built entirely from `ADAPTED` components reads as inheritance on its
own page, which is honest rather than damning.

**A version is native to one desk.** `StrategyPortability` carries a row per
desk, everything but the native one starting `UNPROVEN`; claiming `PORTED`
requires evidence from a run on *that* desk. A component whose declared
assumptions a desk cannot structurally meet is `INAPPLICABLE` — a category
error rather than an untested idea. The inherited corpus covers one market of
seven, and this is where that stops being invisible.

**Lifecycle:**
```
IDEA → CANDIDATE → RESEARCHING → PROMISING → UNDER_REVIEW → VALIDATED
                        ↓            ↓            ↓             ↓
                    REJECTED     REJECTED     REJECTED    PAPER_TRADING
                                                                ↓
                                        MONITORING ⇄ DEGRADED → SUSPENDED
                                                                ↓
                                                            RETIRED
```

**The immutability rule, trigger-enforced:** once a version reaches
`VALIDATED`, its spec and hash cannot change. A **material** change creates a
new `StrategyVersion` at `UNDER_REVIEW` and triggers revalidation. Material =
universe, signal, entry, exit, sizing, cost model, or any parameter that
appeared in a declared cell. Cosmetic changes are recorded as non-material
revisions.

Every result row carries `version_id`, so old results keep pointing at the old
version and cannot be silently restated.

### PromotionGate

`gate_id · version_ref · gate (A..G) · criterion · criterion_digest ·
owner_charter · registered_at · registered_by · evaluated_at · evaluated_by ·
passed · observed · evidence_ref`

Gates are **registered before evaluation**. Default set in
`docs/05-lifecycles.md` §3.

**Written by:** Validation Researcher evaluates; Strategy Committee promotes.

---

## 7. Portfolio, risk and trading entities

```
Portfolio:         portfolio_id · name · desk[] · mode · base_currency
                   initial_equity · allocations[] · constraints
                   mode ∈ {BACKTEST, SIMULATION, PAPER}   ← no LIVE member

Allocation:        portfolio_id · strategy_version_id · weight · capacity
                   rationale · decided_by_meeting

ExposureSnapshot:  taken_at · gross · net · by_desk · by_factor
                   concentration · correlation_matrix_hash

RiskAssessment:    assessment_id · proposal_id · assessor_agent
                   desired_exposure · allowed_exposure
                   limits_applied[] · decision (ALLOW|SHRINK|VETO|HALT)
                   reason · assessed_at

TradeProposal:     proposal_id · portfolio_id · strategy_version_id · desk
                   symbol · desired_exposure · allowed_exposure · final_target
                   rationale_ref · proposed_by

TradeApproval:     approval_id · proposal_id · assessment_id
                   approved_by · approved_at

Order:             order_id · approval_id · symbol · side · quantity
                   submitted_at · broker · status

Position:          portfolio_id · symbol · quantity · avg_price · opened_at

PostTradeReport:   order_id · expected_price · fill_price · slippage
                   cost_attribution · backtest_live_gap
```

Three enforced facts:

1. `RiskAssessment` is written **only** by risk roles. No other agent, ever.
2. A `TradeProposal` without a matching `RiskAssessment` cannot become a
   `TradeApproval` — foreign key plus trigger.
3. An `Order` without an `approval_id` cannot be inserted.

`desired / allowed / final` are all persisted, always — so "risk allowed it"
and "risk was never consulted" are different rows rather than the same silence.

---

## 8. Knowledge entities

```
KnowledgeNode:  node_id · kind (HYPOTHESIS|FINDING|META_FINDING|STRATEGY
                             |LEAD|OBSERVATION|LESSON|DECISION|TRIAL)
                label · family · desk · origin · payload · created_at
KnowledgeEdge:  source · target · kind (SUPPORTS|CONTRADICTS|DEPENDS_ON
                             |SUPERSEDES|CORRELATED_WITH|INSPIRED_BY
                             |REPLICATES|INVALIDATES)
                weight · evidence_ref · note · created_by · created_at
Lesson:         lesson_id · ref · statement · source_ref · author
                standing_rule · applies_to[] · retired_at · retired_reason
CorpusTrial:    trial_id · corpus · ref · hypothesis · title · family
                trial_count · ambiguous_allocation · grade · protocol
                verdict · maturity · dsr · dsr_published · dsr_n_trials
                source · evidence · notes
CorpusRecon.:   corpus · period · digest · claimed_total · claimed_run
                claimed_data_blocked · documented_total
                unallocated · unallocated_reason · entries · documents
Alert:          alert_id · severity · source · subject · message
                recommended_action · raised_at · acknowledged_by
AuditRecord:    record_id · auditor_agent · target · finding · severity
                evidence[] · response_required_from · response · resolved_at
Event:          seq · event_id · actor · subject · kind · payload
                payload_hash · prev_hash · chain_hash · created_at
```

`CORRELATED_WITH` carries the measured correlation and is what stops repeated
observations of one event from counting as independent replication. The
independent-support calculation discounts pairs above a threshold **and reports
what it discounted** rather than silently shrinking a number.

The graph **assigns no confidence scores of its own** — a graph that scores its
nodes invites the reader to trust the score instead of the sources.

`node_id` is the subject's own reference (`HYP-0001`, `MQ-H11`), so an edge
cannot point at something that does not exist. `origin` separates what this
company established from what it inherited, and every node from an import
carries the corpus name.

**Confidence is derived, not stored.** There is no confidence column, and the
absence is the design: a stored band needs somebody to remember to lower it,
and the one time that matters is the time nobody does. `memory/confidence.py`
computes a band — NONE · WEAK · MODERATE · STRONG — from the verdict, the
reportable evidence, the graph's independent-support count, the replications
that held, and the objections still open. Rules are **caps, not contributions**:
evidence raises the band, anything wrong with the finding lowers it, and the
lowest cap wins — so accumulating support can never outvote an unresolved
critical objection. Only the *explanation* is persisted, on
`Finding.confidence_cap_reason`; a stale explanation is cosmetic, a stale band
would not be.

An objection merely **open** lowers the band. It does not have to be upheld or
even tested: the company does not keep believing something at full strength
while a stated, unanswered doubt sits against it, and resolving it either way
lifts the cap.

`CorpusTrial` holds another organisation's figures **as published**. `dsr` and
`dsr_n_trials` travel together and are never recomputed — a deflated Sharpe
means "survived deflation against *that many* trials" — and `dsr_published`
keeps the literal text, because the money column pads the scale to eight places
and "as published" has to survive a round-trip. `CorpusReconciliation` records
what an import claimed against what its documents accounted for; the difference
is carried with the source's own reason, never distributed by guess.

`Event` is append-only (triggers refuse `UPDATE` and `DELETE`) and hash-chained,
with sequence contiguity checked, because deleting a trailing run of events is
the one edit a pure chain cannot detect. **Tamper-evident, not tamper-proof** —
the honest claim.

---

## 9. Who may write what

The table that makes the whole permission model checkable at a glance.

| Entity | Agents may create | Agents may modify | Enforced by |
|---|---|---|---|
| MarketObservation | Intelligence roles | never | append-only |
| Hypothesis | Researchers, Strategy Lab | claim only, pre-registration | trigger |
| Registration | **Registrar only** | **never once locked** | trigger |
| Forecast | any participant, pre-run only | never | trigger |
| Run / Result | **no agent** — engines only | never | `computed_by` CHECK |
| Sealed-split metric | **no agent** — Custodian only | never | CHECK |
| Finding | Analysts, Researchers | author, pre-review | state guard |
| Finding confidence | **no agent** — derived on read | there is no column to modify | absence of a column |
| Evidence | analyst roles, kind-restricted | never | assertion ladder |
| Objection | Critics, Adversarial, Auditors, Skeptic | resolution is the engine's | FK |
| Strategy version | Architect proposes | **never once VALIDATED** | trigger |
| Promotion gate result | Validation evaluates | never | append-only |
| RiskAssessment | **risk roles only** | never | write scope + trigger |
| TradeApproval | Trade Approval Agent | never | requires assessment FK |
| Order | Execution Agent | never | requires approval FK |
| Agent record | **no agent may edit its own** | Org process only | write scope |
| OrgChange | Org Development Lead proposes | decision by meeting | write scope |
| Turn | speaker, through the meeting runtime | never | immutable |
| Decision | Chair / decision-maker | never | append-only |
| CorpusTrial | **no agent** — importer only | never | figures copied as published |
| Knowledge edge | any agent, signed | never | endpoints must exist; correlation must state its weight |
| Lesson / standing rule | any agent, must cite a source | retirement only, with a reason | checked on write |
| Event | **no agent** | never | append-only trigger |

The pattern, in one line:

> **Agents author intent, interpretation, criticism and decisions.
> Software authors fact.**

Every row an agent cannot write is a category of fabrication that cannot occur.
