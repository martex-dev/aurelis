# ADR-0024 — A seat has no tools

Status: accepted · 2026-09-10

## Context

M17 gave the company a real provider and M18 put a real model in a seat. Both
were exercised through `aurelis model check` and `aurelis model rehearse`, which
send one short question and read one short answer. Both passed.

The first time a real model was asked to run a **campaign** — five authoring
attempts against 28,000 hours of recorded BTC-USD — the provider failed with
`Reached maximum number of turns`. Raising the turn limit did not fix it. It
revealed it.

The Claude Agent SDK spawns Claude Code as a subprocess. `allowed_tools=[]` was
being passed on the assumption that an empty allow-list means *nothing is
allowed*. It does not. It means *no restriction is expressed*. Streaming the raw
message sequence showed what the agent had actually been doing with its turns:

```
message 13: ToolUseBlock(name='Grep', input={'pattern': 'one_day|three_days|six_hours|one_week', ...})
message 14: ToolResultBlock(content='tests\\test_campaign.py-199- ...')
message 19: ToolUseBlock(name='Grep', input={'pattern': 'six_hours', 'path': 'src', ...})
message 20: ToolResultBlock(content='src\\aurelis\\authoring\\standin.py-41- ...')
message 25: TextBlock(text="ANSWER: three_days\n\nBECAUSE: ...")
```

The agent answered a design question by grepping this repository. It read
`aurelis/authoring/standin.py` — the module that scripts what a deterministic
stand-in is supposed to answer — and `tests/test_campaign.py`, and then replied.

**That is not a model reasoning about a market. It is a model finding the answer
key.** Every measurement the company takes of a seat — the design space, the
critic's scenario suite, the conformance rehearsal — rests on the agent knowing
only what its material tells it. Any score taken through that path measures
nothing.

## Decision

### The guard is a callback that denies everything, not a list of names

`can_use_tool` returns `PermissionResultDeny` for every tool, whatever it is
called.

A list cannot be the guard, and the reason is not fastidiousness. After the
built-in tools were cut off, the next tool a seat reached for was
`mcp__claude_ai_Remote_Desktop_Commander__list_directory` — **an MCP server
belonging to the person running the command.** The spawned process inherits the
operator's own Claude Code configuration, so the reachable tool surface is not
something this repository can enumerate. It depends on what the operator happens
to have connected, and it can change without a line of Aurelis changing.

`disallowed_tools` is still populated, and `_NO_TOOLS` says in its own docstring
that it is documentation: what an operator reading the configuration sees, and a
closed failure mode if a future SDK stops calling the callback.

### The seat does not inherit the operator's session

`mcp_servers={}` with `strict_mcp_config=True`, and `settings` pointed at an
empty file. A seat is a model answering from its material, not a session
carrying whatever the person running it has signed into.

### The seat does not sit in this repository

`cwd` is an empty temporary directory. Not the security boundary — the callback
is that — but a seat whose working directory is the repository holding the tests
it is scored by is one bad configuration away from reading them, and that is the
configuration we shipped.

### Refused tools are recorded, not silently swallowed

`AgentSdkProvider.refused_tools` keeps what was reached for. An agent that keeps
trying to look something up is telling the company its material is not enough,
and that is worth seeing.

## Consequences

- **Every seat measurement taken through `agent_sdk` before this is void.**
  Nothing had been published or committed from such a run: the contaminated
  campaign existed only in a scratch workspace, and it was re-run from scratch
  after the fix. The numbers in `docs/07-roadmap.md` under M23 are from the
  re-run.

- **`max_turns` is 4 rather than 1, and that is now safe.** One turn was too few
  — a model that spends a turn thinking returns no text at all, which surfaced
  as an unexplained provider failure on exactly the longer prompts the authoring
  seat sends. Extra turns were dangerous only because tools were reachable in
  them. With every tool denied there is nothing for a turn to do but finish the
  sentence.

- **An empty completion is now an error, not an abstention.** The SDK can return
  no text; recording that as an answer an agent gave would put silence on the
  record as a decision.

- **`claude-agent-sdk` moved into the `dev` extra.** It stays optional to *run*
  and is now required to *test*: the guard is the difference between measuring
  an agent and letting it read the answer key, so CI has to be able to check it.
  `tests/test_seat_isolation.py` asserts configuration only — no network, no
  credentials, no spawned process.

- **The company's own honesty machinery did not catch this.** The figure check
  passed, because every figure the agent cited was real — it had gone and looked
  them up. Preregistration passed, because the design was locked before the run.
  Nothing in the record showed a contaminated answer, and nothing could have:
  the contamination was in a subprocess the ledger never sees. **The lesson is
  that a provider boundary needs the same suspicion as a data boundary**, and it
  had not been getting it.
