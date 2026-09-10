# 08 — Operations

Date: 2026-09-07
Status: current as of M13.

How to run Aurelis, what to check, what to do when something is wrong, and —
just as important — what this system is **not** yet safe to do.

---

## 0. The short version

```bash
pip install -e ".[dev]"
aurelis db init                 # schema, invariants, the org chart
aurelis doctor                  # is this workspace healthy?
aurelis agent hire              # staff the launch roster
aurelis desk open all           # open the seven desks
aurelis orgdev scale            # staff them, through the org-change lifecycle
aurelis station serve           # Mission Control on http://127.0.0.1:8787/
```

Everything runs offline against the mock provider by default. No credentials,
no network, no cost.

---

## 1. Before you start: what this cannot do

Read this section before anything else.

**There is no live trading.** Not disabled — absent. No `LiveBroker`, no
`BrokerKind.LIVE`, no registry entry, and `resolve("live")` refuses with an
explanation rather than a `KeyError` (ADR-0006). A test parses every module's
imports to prove nothing can reach a live adapter.

**There is no live market data.** All seven desks run on fixtures:
deterministic, offline, shaped like the desk but not a market. Every artifact
records `is_live: false`; every desk's readiness check records its data as
`PROVISIONAL` rather than a pass. `aurelis desk feeds` prints the state of every
one.

**Nothing here is proven profitable**, and the system is built so it can say so.
Of the seven desks' first research missions, all seven returned `UNDERPOWERED`.
That is the honest answer to the question that was asked with the data
available.

---

## 2. Daily checks

### `aurelis doctor`

The single command to run first. It checks dependencies, the workspace, the
schema, every invariant trigger, the org registry and the engines. Exit codes:
`0` healthy, `1` a problem you must repair, `2` misuse.

The trigger counts are the ones to watch. If any line reads `MISSING`, a
guarantee this system rests on is not in force:

| Check | What is not true if it is missing |
|---|---|
| append-only triggers | The ledger can be edited without detection |
| write-scope guards | An agent can write outside its charter's authority |
| preregistration | A run can precede its registration |
| onboarding gate | An agent that failed the scenario suite can start work |
| coverage conservation | A charter can be orphaned; a locked prediction can be re-aimed |

Repair is `aurelis db init`, which is idempotent and safe against a live
workspace.

### `aurelis ledger verify`

Re-reads and re-hashes the whole chain. Run it in CI and after any restore.

> Tamper-**evident**, not tamper-proof. Edits are detectable, not impossible.
> Anyone with write access to the file can change it; they cannot change it
> without the chain saying so.

### `aurelis db verify`

The chain *plus* every artifact digest re-checked against its bytes. The
artifact store is content-addressed, so a file's name is the hash of its
contents and corruption is caught exactly rather than approximately.

---

## 3. Backup and restore

```bash
aurelis db backup /backups/aurelis-2026-09-07
aurelis db restore /backups/aurelis-2026-09-07 -w /new/workspace
```

**Do not copy `aurelis.db` with `cp`.** A copy taken mid-transaction opens
without complaint and is missing the last write — the kind of corruption only
discovered when the backup is needed. `aurelis db backup` uses SQLite's own
backup API, which takes a consistent snapshot under a read lock.

A backup is a directory containing the database, the object store, and
`aurelis-backup.json` — a manifest recording the event count and the chain
head. **Restore refuses without it**, because a restore that only reports "a
file opened" has checked nothing. On restore the chain is re-verified, every
artifact is rehashed, and the counts are compared against the manifest. Any
mismatch exits non-zero.

Back up **both** the database and the object store. Artifacts are cited by
digest from database rows; a database without its blobs restores to a record
full of dangling citations, and `db verify` will say so.

---

## 4. Letting it run itself

```bash
aurelis run -w live --snapshot SNP-0001 --cycles 10
```

Each cycle: assess the mandate, take the first action aimed at something unmet,
check whether it moved. It stops when every action that could help has been
taken, and prints a reason for each condition it gave up on.

**It will not repeat a search.** A second campaign widens the declared space,
which raises the surplus the best design has to clear — faster than searching
finds anything. This is the property the whole layer exists for, and it is why
a run that does almost nothing is often the correct outcome.

Two bounds beyond that: `--cycles` caps decisions, `--calls` caps model calls
and stops *before* the limit rather than through it.

It cannot fetch data — that reaches outside the company and needs a person —
and it cannot trade, because no live adapter exists.

---

## 5. Running work

### Multi-worker execution

Workers claim tasks from the durable queue. The claim is a **compare-and-set**:
a conditional update that only succeeds if the row is still queued.

This was broken until M13 and broken *silently*. The claim used to select a
candidate and then write `CLAIMED` onto it, on the theory that Postgres'
`SKIP LOCKED` and SQLite's single-writer model each made that safe. The second
half was false — SQLAlchemy opens a DEFERRED transaction on SQLite, so the
SELECT took no lock. Eight workers against forty tasks produced **fifty-three
claims and no error**: thirteen tasks done twice, each with its own budget draw.

If you are running multiple workers, the guarantee you have is that a task is
claimed once. What you do **not** have is automatic recovery of a worker that
dies mid-task — see below.

### A worker that dies

A task claimed by a process that never returns stays `CLAIMED` forever.
`aurelis tick` reclaims them as part of its cycle — it calls
`TaskQueue.cancel_stranded`, which returns tasks held past their lease to the
queue and reports how many:

```bash
aurelis tick --rounds 1           # scheduler pass; reclaims stranded tasks
```

Reclaiming is tied to a scheduler pass rather than run on a timer, on purpose: a
task returned to the queue while its original worker is merely slow gets done
twice, which is precisely what the compare-and-set above exists to prevent.

### Budgets

Every task carries an allowance and every model call draws against a scope
envelope. A task refused for budget is a **terminal status**, not an error —
running out of money is a legitimate outcome and the record says so.
`aurelis doctor` reports the company envelope and what has been drawn against
it.

---

## 6. Growing the company

The company hires on measured evidence, not on a plan.

```bash
aurelis orgdev metrics            # what it can measure about itself
aurelis orgdev scan               # which declared triggers fire
aurelis orgdev develop            # propose, decide, apply, measure
aurelis orgdev scale              # staff open desks that nobody covers
aurelis orgdev changes            # every change, and what it actually did
```

Coverage is `(charter, desk)`. Thirteen of the seventy-six charters are
desk-specific, so seven open desks means **154 jobs**, not 76. `aurelis orgdev
metrics` prints the census; a slot held by nobody is a trigger, and a slot held
by two people is a bug.

**Every structural change is preregistered** (ADR-0012). The predicted metric,
direction, magnitude and measurement plan are hashed before the Board sees them
and frozen by a trigger afterwards. Some changes are recorded as failures. That
is the intended output — the first change the company ever made to itself is
recorded as `no_change`.

---

## 7. Deployment

### SQLite (default)

One file plus an object store. Correct for a single operator and one worker
process. WAL is enabled, so readers do not block the writer.

### Postgres

Set `AURELIS_DATABASE_URL` to a Postgres URL. Every invariant in this system
has a Postgres implementation written alongside its SQLite one, and the claim
`SKIP LOCKED` makes about concurrency is genuinely true there.

> **Honest status: the Postgres paths are written and are not exercised by
> this repository's CI.** They are read-reviewed, not run. Before trusting a
> Postgres deployment, run the full test suite against it with
> `AURELIS_DATABASE_URL` set, and expect to fix things — the `Money` columns
> are TEXT, several CHECK constraints cast, and the JSON columns are
> `sa.JSON` rather than `JSONB`.

Move to Postgres when you want more than one worker process, not before.

### The station

```bash
aurelis station serve --host 127.0.0.1 --port 8787
```

Loopback by default and read-only by construction: it serves projections and
implements `do_GET` and nothing else (ADR-0009). It has **no authentication**.
Do not bind it to a public interface.

---

## 8. When something is wrong

| Symptom | Where to look |
|---|---|
| `doctor` reports a missing trigger | `aurelis db init` — idempotent |
| `ledger verify` reports a break | The chain names the sequence number. Restore from backup; do not "repair" the ledger |
| `db verify` reports a digest mismatch | An artifact's bytes changed. Restore that blob from backup |
| An agent cannot write something | It is working as designed. `aurelis agent show <ref>` prints the resolved authority and where it came from |
| An agent will not become active | Its training run failed. `aurelis training record <ref>` says which questions it got wrong |
| A desk will not open | `aurelis desk show <desk>` prints all nine checks and which one failed |
| A task is stuck `CLAIMED` | The worker died. `aurelis tick` reclaims tasks held past their lease |
| The queue looks empty but work is pending | Unmet dependencies make a task invisible rather than claimable |

**Do not repair the ledger.** It is the record the whole system's credibility
rests on. A broken chain means either corruption (restore) or tampering
(investigate); editing it to verify again destroys the only evidence of which.

---

## 9. Running it on a real model

The whole system runs offline for free, and that stays the default. To put real
models in the seats on a Claude subscription:

```bash
pip install -e '.[subscription]'          # the Claude Agent SDK
claude                                     # sign in once, then exit
export AURELIS_PROVIDER=agent_sdk          # or AURELIS_PROVIDER=anthropic_api
aurelis model check -w live --yes          # one real call, end to end
```

`aurelis doctor` reports the provider and whether the SDK is installed. It does
**not** report whether you are signed in — the SDK spawns Claude Code as a
subprocess, and whether that process is authenticated is only knowable by
making a call. That is what `model check` is for.

### What it costs

Very little, because the deterministic work is done in software. Measured on a
full pipeline:

| step | model calls |
| --- | --- |
| `demo` + `agent hire` | 4 |
| `strategy author` | 6 |
| `strategy campaign --budget 5` | 14 |

Under a subscription every call reports `usd = 0`, which is true rather than
missing: the scarce resource is allowance, and the budget ledger meters tokens
separately for exactly that reason. Token counts on that path are **estimates**
— the SDK does not always report usage — and `Usage.estimated` says so
wherever a number surfaces.

### A seat has no tools

The provider denies every tool the model reaches for, refuses to load the
operator's MCP servers or settings, and runs in an empty directory. This is not
hardening for its own sake: without it the agent answers design questions by
grepping this repository, including the module that scripts what a stand-in is
supposed to say. See [ADR-0024](adr/0024-a-seat-has-no-tools.md).

`aurelis model rehearse --seat author` measures whether a real model's answers
can be *used* before you spend a campaign on it. It is cheap and it has caught
a 0/5 before.

---

## 10. Cost

Everything in CI runs against the mock provider: no credentials,
no network, zero cost. Switching to a real provider is a configuration change,
and the guards that keep it affordable are already in force — model routing by
charter tier, response caching, per-task allowances, per-scope envelopes, and
experiment deduplication by spec digest.

`aurelis doctor` reports the company budget and what has been drawn against it;
the Mission Control station shows spend per agent and per department.

---

## 11. What is on the other side of M13

Stated plainly, because a system that hides its gaps is worse than one that
lists them:

- **No live data feed on any desk.** The declared sources are named in the desk
  registry; none is wired.
- **No desk-specific training scenarios.** The M10 catalogue is twelve
  crypto-shaped worlds, so an agent on the FX desk is scored on another desk's
  questions.
- **`CAPACITY_IGNORED` has no scorable scenario.** The plant is in the
  catalogue and measurement says it did not take.
- **The options desk cannot compute a greek.** A typed refusal — that desk is
  researchable as a price series and not as an options book.
- **Postgres is written and unexercised.**
- **No automatic recovery of a dead worker.** Stranded tasks are returned
  manually, on purpose.
- **Nothing behind either agent seat is a model, offline.** `aurelis training
  seat` and `aurelis strategy author` run a deterministic stand-in whenever the
  provider is `mock`, which is what CI and every offline demonstration use.
  Point `AURELIS_PROVIDER` at a real provider and the seats get that instead —
  see section 8. The machinery is
  real; the reasoner is not, and both commands say so in their own output.
- **No authored strategy has survived its own search.** One campaign has
  reached a design that beat buying and holding; corrected for how wide the
  search was, its surplus is negative. The company has created nothing it can
  claim, and the record says so rather than reporting the maximum.
- **Nothing reviews an authored strategy.** The M14 critic could sit over an
  authored version and does not. The campaign picks its own next revision.
- **A campaign is one desk over fixture data.** The correction is arithmetic
  about a search, not evidence about a market.
- **A real model has answered, and the seats hold.** Sign in with
  `claude auth login`, then `aurelis model check --yes`. `aurelis model
  rehearse --seat author --yes` reports whether a seat's answers are usable —
  run it after any prompt change, because a guard that silently rejects most of
  what a model says leaves a seat that looks occupied and produces nothing.
- **No seat has been scored against measured truth with a real model in it.**
  Conformance says an answer is usable, not that it is right. The M10 scenario
  suite would settle that and has not been pointed at a model yet.
- **Self-improvement is structural so far.** `aurelis orgdev retier` reduces how
  many charters run above their written tier, and the company measures it. No
  agent has been shown to *research better* after a reorganisation — scoring an
  agent, splitting it and scoring it again would settle that, and has not been
  done.
- **No money saved has been observed.** Under a subscription every call reports
  zero marginal cost. The tier saving is structural and the rate table says what
  it is worth on the metered path; the company does not print a figure it never
  measured.
- **The company says it is not ready, and names why.** `aurelis mandate assess`
  checks ten conditions declared in advance. Nothing is *blocked* any more:
  every condition it misses is a research result rather than a missing
  capability.
- **Real market data enters through `aurelis data fetch --yes`.** It is the one
  command in the repository that reaches a market — public, unauthenticated,
  and it asks before it goes. What it stores is a hashed recording, not a
  connection: research runs against the snapshot, because an experiment cannot
  be reproduced against a moving endpoint. `aurelis data snapshots` shows what
  is held and whether each still verifies.
- **Real data does not make the research powered.** Four months of hourly bars
  against the fifteen years the power calculation says the claim needs.
- **`aurelis trading readiness` says what stands in the way.** Seven promotion
  gates, each answered from the record with a number or with a silence naming
  what is absent. A silence is not a zero: two gates today cannot be asked at
  all, and a gate nobody can answer cannot be passed.
- **`aurelis trading deploy` refuses, and the refusal is the product.** The
  authored designs do not clear their own gates. `risk_cleared` and
  `paper_gap_measured` are downstream of promotion, so they stay unmet — a
  command that produced a risk assessment for a version the gates rejected
  would be manufacturing exactly the evidence the mandate asks for. What
  changed at M22 is that an operator can see *why*, gate by gate, instead of
  reading "0 risk assessments".
- **There is no sealed-query mechanism.** Gate F's criterion counts queries and
  is satisfied by zero, but its own note requires that one happened and passed.
  The reader returns silence rather than the zero it would accept, and the hole
  is named here rather than closed quietly.
- **Token counts on the subscription path are estimates.** The SDK does not
  always report usage, so the provider counts characters. `Usage.estimated`
  carries it and `aurelis model check` prints it — a budget enforced there is
  enforced on an approximation.
