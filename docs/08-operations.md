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

The first thing it does, when a market has been recorded, is seat its judging
agents: every agent in Market Intelligence, Quantitative Research and the
Strategy Laboratory states one view per recorded market, and the loop stops
seating when they all hold one. That is the forward record accumulating, and
it cannot be hurried.

## 4a. The forward record

```bash
aurelis data fetch -w live --symbol ETH-USD --bars 400 --yes   # a view needs a recording
aurelis thesis seat -w live --agent INTEL --agent QUANT --agent STRAT
aurelis thesis list -w live
aurelis thesis resolve -w live --fetch --yes                   # once a horizon has passed
aurelis thesis calibration -w live
```

A view is a market, a horizon, a direction and a confidence, sealed and hashed
before the outcome exists. The database refuses to edit, rescore or delete it.
`resolve` reads recordings only; `--fetch --yes` records the instruments with
due views first, which is the one step that reaches a market.

The measure is calibration, not P&L. `calibration` prints the mean Brier
score (0.25 is always saying 50%), the hit rate, what always predicting the
observed up-frequency would have scored, and stated-against-observed by
confidence band. A record that beats the coin toss but not the base rate has
learned the drift of the market and nothing else.

Offline, `aurelis data record-fixture` records a desk fixture as a snapshot
marked as not a market. Views on it are shown and labelled, and never counted
toward the mandate.

## 4b. Running it for days

```bash
aurelis service grant -w live --source coinbase --instrument BTC-USD --instrument ETH-USD \
    --reason "the forward record needs fresh recordings every wake" --by <you> --yes
aurelis service start -w live --every 1h --for 7d --calls-per-day 200
aurelis service status -w live
```

A grant can also be drawn from the venue's own liquidity ranking instead of
typed:

```bash
aurelis service universe --quote USD --top 30            # show the ranking; writes nothing
aurelis service grant -w live --universe USD --top 30 \
    --reason "a mechanism is a claim about an event, tested wherever it fires" --by <you> --yes
```

The ranking is by dollar notional over the last day (by units a memecoin
outranks bitcoin), and any instrument whose 24h range was under 0.2% is set
aside as pegged — a stablecoin is liquid and not a market. The instruments
that come out are the grant, as fixed as a typed list; the rule and the
ranking's artifact digest are recorded on it as provenance. The service never
re-runs the rule: a listing that becomes liquid later is not fetched until a
person grants again. An instrument on two grants is fetched once a wake.

Leverage is its own grant, on the same spot symbols:

```bash
aurelis service grant -w live --source bybit --from-grant GRT-0002 \
    --reason "the leverage the agents keep citing, read for the same universe" --by <you> --yes
```

Every wake it reads each instrument's USDT perpetual on Bybit's public API —
the funding rate per settlement and the hourly open interest — and records
them as events on the spot instrument, with extreme funding and open-interest
surges derived. A symbol with no perpetual is counted in the wake's note; a
venue that is down is one warning incident. A leverage grant fetches no bars.

The grant is the one decision a person makes: it names the vendor, the
instruments, who and why, goes on the ledger, and cannot be widened — only
revoked (`aurelis service revoke GRT-0001`). The service then wakes on the
interval: fetch under the grants, settle every view a recording covers, run
the loop inside what is left of the daily model-call budget, and write a row
per wake. Ctrl-C stops it and the reason is recorded.

A vendor that is down is a warning alert raised by the Operations Director and
the wake continues; a model out of allowance is a failed action on the loop's
record and the next wake retries. `service status` and the station's
`/service` page show the grants, the wakes and every incident still open.

Runs in a terminal in the foreground; a process manager or a screen session
keeps it up across a logout. It cannot trade.

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
  checks eleven conditions declared in advance. Nothing is *blocked* any more:
  every condition it misses is a research result rather than a missing
  capability.
- **Real market data enters through `aurelis data fetch --yes`.** It is the one
  command in the repository that reaches a market — public, unauthenticated,
  and it asks before it goes. What it stores is a hashed recording, not a
  connection: research runs against the snapshot, because an experiment cannot
  be reproduced against a moving endpoint. `aurelis data snapshots` shows what
  is held and whether each still verifies.
- **Six agents, one opinion, now attacked.** The first seven agents seated
  on a real model read the same twenty-four closes and all said *down*. Since
  M28 a critic attacks every view before the seal and the author answers; the
  first real attack moved a view from 0.55 to 0.52. The critic reads the same
  evidence the author did, so this tests reasoning, not independence of
  evidence.
- **The forward record is empty until a horizon passes.** The live workspace
  holds sealed views; the first resolve on 2026-09-11 at 19:00Z. A running
  service settles them on its next wake; otherwise `aurelis thesis resolve
  --fetch --yes`.
- **The service wakes on a clock only.** Not on a market event, not on
  another agent's finding. Those are the next things the brief asks for.
- **A scheme trades on paper only once it has earned it.** Twenty scored
  out-of-sample predictions beating the instrument's own drift; then five
  percent of the paper book, through Risk. `aurelis mechanism trades` shows
  the round trips and realised P&L, which is reported and never judged.
- **The book and the tape are read hourly, not streamed.** Depth and taker
  flow enter as events on every wake for every granted instrument; a
  microstructure edge on a faster clock is not something an hourly reading
  can see. `--every 15m` is the floor.
- **The world model holds the venue and what recordings imply, nothing
  off-venue.** `aurelis world sync --yes` reads the public catalogue;
  `world derive` adds volume spikes and range breaks from a recording; the
  service does both every wake. No social, on-chain or filing source exists
  yet. `world cooccur` lists conjunctions and says they are not discoveries.
- **Agents write rules; the menu is gone.** `aurelis strategy author` seats
  an agent to write a rule in the company's rule language (`aurelis.rules`),
  one declared cell per rule. Attempts recorded before M26 hold a menu pick
  and cannot be deployed; their rows stand.
- **A campaign's declared width is a floor.** It is the number of rules the
  campaign let itself write. What a model weighed before writing one down is
  uncounted, and the forward record is the check on that.
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
