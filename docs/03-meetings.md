# 03 — Meetings & Collaboration

Date: 2026-09-04
Status: proposal, v2.

Meetings are how this company thinks together. Agents brainstorm, argue,
present evidence, change each other's minds, and decide. The transcript is
kept — it is part of the company's record, and reading it is one of the things
Mission Control is *for*.

This document specifies how a meeting works so that it produces real work
instead of expensive theatre.

---

## 1. The rule that makes meetings worth having

> **Every meeting ends in state changes, and the state changes are typed
> records — not a summary paragraph.**

A meeting that produces no task, no decision, no experiment, no revision and no
recorded disagreement is logged as **unproductive**, and that number is a
metric on the Chair and on the meeting type. Meeting types that keep coming out
unproductive get their protocol changed or get stopped.

That single rule is what separates this from roleplay. Everything below is in
service of it.

---

## 2. Meeting types

| Type | Trigger | Participants | Rounds | Produces |
|---|---|---|---|---|
| **Kickoff** | Every mission and project starts | Assigned team + department heads | 5 | Plan, hypothesis backlog, task assignments, budget split, forecasts |
| **Standup** | Scheduled, cheap | One team | 1 | Status deltas, blockers, reassignments |
| **Brainstorm** | Research Director or Head of Strategy calls it | Cross-department, deliberately mixed | 4 | Candidate hypotheses, leads, research directions |
| **Research Review** | A finding is ready or contested | Author, Critic, Statistician, Auditor, Lead | 6 | Verdict on the finding, objections with tests, follow-ups |
| **Debate** | Unresolved disagreement or a contested claim | Two sides + Chair + neutral Auditor | 6 | Position record, discriminating tests, decision, preserved dissent |
| **Strategy Committee** | A strategy requests promotion | Head of Strategy, Validation, Risk, Audit, CIO | 6 | Promotion decision against the gates, or the specific reason it failed |
| **Risk Committee** | Limit change, exposure breach, new deployment | CRO, Risk, PM, Exposure, Correlation, Head of Trading | 4 | Limits, vetoes, mandated reductions |
| **Incident Review** | Alert, breach, data failure, live divergence | Whoever is implicated + Audit + Ops | 4 | Root cause, corrective tasks, standing rule |
| **Retrospective** | Every mission and project ends | Everyone who worked on it | 4 | Lessons to memory, org change proposals, calibration review |
| **Board** | Weekly, plus escalations and org changes | Executive + all department heads | 6 | Mission portfolio, priorities, org changes, budget |
| **All-Hands** | Monthly or on a major result | Everyone | 3 | Company state, direction, recognition of good failures |

**Kickoff and Retrospective are mandatory** on every mission and project. That
is the "meet at the start and meet at the end" pattern — enforced by the
mission state machine, which cannot leave `PLANNING` without a Kickoff and
cannot reach `CLOSED` without a Retrospective.

Everything between them runs on individual work, messages and channels, with
the heavier meeting types called when they are needed.

---

## 3. The meeting protocol

Every meeting runs the same seven phases. Types differ in which phases are
enabled, how many exchange rounds they get, and who may speak in each.

```
┌─ 0. CONVENE ────────────────────────────────────────────────────────────┐
│  Deterministic. The Chair assembles:                                     │
│    · agenda (from the trigger + open action items)                       │
│    · EVIDENCE PACK — every relevant artifact, finding, metric and prior   │
│      decision, pre-fetched with hashes                                    │
│    · participant list, round cap, token budget                           │
│  Costs nothing. No model call.                                           │
├─ 1. BRIEF ──────────────────────────────────────────────────────────────┤
│  Deterministic. The state of the world, rendered from the record:        │
│  what is known, what is being asked, what was decided before, what       │
│  failed before. Agents read the same brief — no information asymmetry     │
│  by accident.                                                            │
├─ 2. FORECAST ───────────────────────────────────────────────────────────┤
│  Each participant privately records a probability for the outcome,        │
│  BEFORE hearing anyone. Cheap (low tier). Scored later. This is the      │
│  company's honest quality signal and it costs almost nothing.            │
├─ 3. OPENING ────────────────────────────────────────────────────────────┤
│  One bounded turn each. Position, key evidence refs, what would change   │
│  their mind. Everyone speaks exactly once.                               │
├─ 4. EXCHANGE ───────────────────────────────────────────────────────────┤
│  The actual discussion. N rounds, capped. Participants see each other's  │
│  turns and respond. Brainstorming, challenge, building on ideas.         │
│  The Chair selects who speaks each round — normally those in genuine     │
│  disagreement, plus anyone directly asked a question.                    │
├─ 5. CHALLENGE ──────────────────────────────────────────────────────────┤
│  Objections are formalised. Each must carry a DISCRIMINATING TEST:       │
│  an executable spec that would settle it. The Chair dispatches every     │
│  test that fits the meeting's compute budget; results come back into     │
│  the room if they finish in time, otherwise as follow-up tasks.          │
├─ 6. SYNTHESIS ──────────────────────────────────────────────────────────┤
│  The Chair (or the senior decision-maker for this type) drafts the       │
│  outcome: what was agreed, what remains contested, what is decided.      │
├─ 7. DECIDE & ASSIGN ────────────────────────────────────────────────────┤
│  Typed Decision record with DISSENT PRESERVED — who disagreed, why, and  │
│  what evidence they cited. Action items become real Task rows with       │
│  owners and deadlines. Forecasts are scored against the outcome.         │
└──────────────────────────────────────────────────────────────────────────┘
```

### Why phase 5 has teeth

An objection that must carry a test that would settle it is the difference
between a meeting and an argument. "I'm worried this is overfit" is not an
objection. "Re-run this with a point-in-time universe and the Sharpe will drop
below 1.0" is — and the Chair runs it, in the meeting, and everyone sees the
answer.

That mechanism is why the debate ends in evidence instead of ending when
someone gets tired.

---

## 4. What a turn looks like

Every contribution is a typed artifact, which is what makes the transcript
queryable and the meeting auditable.

```
Turn:
    turn_id · meeting_id · round · phase
    speaker_agent · addressed_to[]
    kind      POSITION | ARGUMENT | QUESTION | ANSWER | EVIDENCE
              | OBJECTION | CONCESSION | PROPOSAL | SYNTHESIS
    body                    natural language — this is a real conversation
    claims[]                each factual claim, separately extracted
    evidence_refs[]         artifact hashes / finding ids per claim
    stance                  SUPPORTS | OPPOSES | ABSTAINS | UNCERTAIN
    changed_mind_from       set when a participant moves position
    tokens · cost
```

Two validators run on every turn:

1. **Numbers must be sourced.** A figure in a turn body that does not appear in
   the evidence pack or in a tool result from this meeting is rejected. Agents
   quote the record; they do not recall numbers.
2. **Claims must be typed.** A factual claim without an evidence ref must be
   explicitly marked as opinion, speculation or a question. This is not
   censorship — speculation is genuinely useful in a Brainstorm, and marking it
   is what keeps it from hardening into a fact three meetings later.

`changed_mind_from` is deliberately tracked. An agent that updates on evidence
is doing the job; an agent that never updates, or always updates, is a measured
problem.

---

## 5. The Chair

The Chair is partly deterministic software and partly the Chief of Staff agent.

**Deterministic (no model call):**
- assembling the evidence pack and the brief
- enforcing round caps, token budgets and turn limits
- selecting speakers by stance conflict and by direct address
- dispatching discriminating tests
- extracting claims, evidence refs and stances from turns
- creating Task rows from action items
- scoring forecasts
- computing the productivity metric

**Model-driven (Chief of Staff, mid tier):**
- drafting the synthesis
- deciding when a discussion has converged early
- deciding when to escalate an unresolved disagreement to a higher meeting

Splitting it this way means most of the Chair costs nothing, and the parts that
cost money are the parts that need judgement.

---

## 6. Cost control

Meetings are the most expensive thing the company does. They are budgeted like
anything else.

### Per-meeting budget

Declared at CONVENE, enforced by the Chair:

```
MeetingBudget:
    max_participants        typically 4–8; All-Hands is the exception
    max_exchange_rounds     3–6 by type
    max_tokens_total        hard cap
    max_tokens_per_turn     keeps one agent from consuming the room
    max_test_dispatches     compute budget for discriminating tests
    tier_policy             who gets which model in which phase
```

When the budget is exhausted, the Chair moves straight to SYNTHESIS and the
unfinished threads become follow-up tasks. Running out of meeting is a normal
outcome, not a failure.

### The cost ladder

| Phase | Tier | Why |
|---|---|---|
| CONVENE, BRIEF | none | Deterministic |
| FORECAST | low | One probability each |
| OPENING | mid, low for junior | One bounded turn each |
| EXCHANGE | mid; high for the two principals in a Debate | Where the thinking happens |
| CHALLENGE | mid | Objections are structured |
| SYNTHESIS | mid | One draft |
| DECIDE | none | Typed extraction |

### Attendance discipline

Not everyone attends everything. Participation is resolved from the subject:

- **Required** — anyone whose write scope covers the decision (Risk for a risk
  decision, Head of Strategy for a promotion).
- **Contributing** — those with relevant evidence or genuine stance conflict.
- **Observing** — receives the minutes, does not speak, costs nothing.

At Stage 5 with a hundred agents, a Research Review still has six people in the
room and ninety-four reading the minutes. That is how real companies scale
meetings and it is how this one does too.

---

## 7. Minutes and the record

Every meeting produces:

```
Meeting:
    meeting_id · type · subject · trigger
    mission_id · project_id · desk · department
    chair · participants[] (with roles at the time)
    agenda[] · evidence_pack[] (hashes)
    turns[]                      the full transcript
    forecasts[] · forecast_scores[]
    objections[] · discriminating_tests[] · test_results[]
    decisions[] · dissent[]
    action_items[] → Task rows
    tokens · cost · duration
    productive: bool             ≥1 state change
```

The transcript is **kept in full and is readable in Mission Control**. Clicking
a meeting shows the room, who said what, who changed their mind, what evidence
was cited, what was decided, and who disagreed.

The minutes are extracted deterministically from the turns, so the summary
cannot disagree with the transcript.

---

## 8. How meetings connect to the work

```
MISSION OPENS
    │
    ├─▶ KICKOFF ────────────────────▶ plan · hypotheses · tasks · forecasts
    │                                          │
    │        individual work, messages, channel posts, engine runs
    │                                          │
    ├─▶ BRAINSTORM (as needed) ─────▶ new hypotheses, new directions
    ├─▶ STANDUP (scheduled) ────────▶ blockers, reassignment
    ├─▶ RESEARCH REVIEW (per finding) ▶ verdict, objections, follow-ups
    ├─▶ DEBATE (on deadlock) ───────▶ discriminating tests, decision, dissent
    ├─▶ STRATEGY COMMITTEE ─────────▶ promotion or specific refusal
    ├─▶ RISK COMMITTEE ─────────────▶ limits, vetoes
    │                                          │
    └─▶ RETROSPECTIVE ──────────────▶ lessons → memory
                                      calibration review
                                      org change proposals → Board
MISSION CLOSES
```

The Retrospective is where the company learns. It reviews what was predicted
against what happened, extracts lessons into institutional memory as standing
rules, and — critically — feeds the Org Development Lead with the evidence for
structural change proposals.

---

## 9. Brainstorming, specifically

The user asked for a company that invents things. Brainstorm meetings are built
for divergence, and they run under different rules from the rest:

- **Speculation is allowed and encouraged**, marked as such. Nothing said in a
  Brainstorm can become evidence for anything; ideas leave as `LEAD` nodes in
  the knowledge graph, never as findings.
- **Deliberately mixed attendance.** A Brainstorm on options volatility pulls
  in the crypto Technical Analyst and the Macro Analyst on purpose — the
  cross-desk transfer is the point.
- **No decision required.** A Brainstorm's productive output is candidate
  hypotheses, and it is productive if it produces any.
- **Prior art is pre-loaded.** The Knowledge department injects "we tried this
  before, here is what happened" into the evidence pack automatically. This is
  the single most valuable thing institutional memory does — 174 trials of
  graveyard is exactly the context a brainstorm needs to not repeat itself.
- **Novelty scoring.** Candidate hypotheses are checked against the ledger for
  duplication before they consume research budget.

---

## 10. Failure modes, and what stops them

Meetings between LLM agents have known ways of going wrong. Each gets a
mechanism, not a warning.

| Failure | Mechanism |
|---|---|
| Agreement cascade — everyone agrees with the first speaker | Private forecasts recorded in phase 2 **before** anyone speaks; opening turn order randomised; adversarial roles pinned to a different model family |
| Endless discussion | Hard round and token caps; the Chair moves to synthesis on exhaustion |
| Persuasion beating evidence | Numbers must be sourced; objections must carry tests; the test result decides |
| Fabricated figures | Turn validator rejects unsourced numerals |
| Consensus by attrition | Dissent is a stored field on the Decision, permanently |
| Roleplay with no output | Productivity metric per meeting and per Chair; unproductive types get changed or stopped |
| Cost blowout | Budget declared at convene, enforced per turn, tiered by phase |
| The loudest agent dominates | Per-turn token cap; the Chair selects speakers by stance conflict, not by eagerness |
| Meetings for their own sake | Only Kickoff and Retrospective are mandatory; everything else needs a trigger |
| Same debate every month | Prior decisions are in the evidence pack; re-opening a settled question requires a stated new reason |

---

## 11. What this gives you

A company where agents genuinely work together: they observe, they bring
findings to each other, they argue, they run tests to settle arguments, they
change their minds on evidence, they decide, they disagree on the record, and
they go away with assignments.

And every one of those conversations is a durable, queryable, auditable object
that Mission Control can render — so you can open a meeting from three weeks
ago and see exactly why the company believes what it believes.
