# ADR-0063 — Talking to the agents

Status: accepted · 2026-10-18

## Context

The operator wanted a workspace where they can click an agent and talk to it.
The answer had to come from the agent itself, not from a separate assistant
describing the agent. Until now the only way to reach the agents was a
Markdown file dropped in the brain's Inbox: a letter, with no reply.

## Decision

**Clicking an agent in the Office opens a conversation with it** (a *talk*
tab, beside its profile).

- **The agent answers as itself, from its own seat.** Its system prompt holds:
  - who it is (`identity_of`: handle, department, charters);
  - its current method (M48);
  - the shared brain every seat reads (M46);
  - a conversation preamble (`chat/talk.py: CHAT_SYSTEM`).

  Its prompt holds its own record (calibration and its most recent scored
  views), its latest notes, the last twelve turns of the conversation, and
  what the operator just said. The model is routed by the agent's tier,
  exactly as its work is.
- **Both sides are on the record, append-only.** That means a `chat_turns`
  row each, protected by triggers, plus a ledger event each: `chat.asked`
  (actor OPERATOR) and `chat.answered` (actor the agent). The operator's line
  is committed before the model is asked, so it stands even when no answer
  comes. The model is asked outside any write, so a slow answer never holds
  the database against the hourly service.
- **A conversation cannot act.** No tool is offered. The seat is the same
  sandbox as every seat (ADR-0024). Nothing said becomes a view, an order, a
  grant or a change, and a test asserts those tables do not move. An
  instruction is recorded as said. Turning instructions into work is the
  Company Manager's job (M63).
- **Figures are flagged, not refused.** A sealed view citing a number it was
  not shown is refused. A conversation that went silent whenever a number was
  rounded would be useless. So each answer stores the numerals that were not
  in its material, and the Office shows them under the answer.
- **The answering provider and model are shown.** The talk tab says which
  provider answers. When it is the offline stand-in, it says so in red. Each
  answer is labelled with the model that wrote it. The first live test
  answered from the mock, because the test station had been started without
  `AURELIS_PROVIDER=agent_sdk`; that stand-in line is on the record labelled
  `mock`. Both labels exist because that happened.
- **The station accepts one POST.** It is `/office/chat/<agent>`, and it must
  carry a JSON body and an `X-Aurelis-Office: 1` header. Another web page
  open in the same browser cannot set that header without a CORS preflight,
  and the station answers none. So nothing but the Office's own page can make
  the company spend a model call. Bodies are capped at 8 KB.

## Consequences

- The operator can ask any agent what it is doing, why it declined a market,
  or what it thinks of its own record, and get an answer grounded in that
  record. The first real exchange was with the Critic. It reported its five
  most recent scored calls were all wrong, and that its lifetime Brier of
  0.2527 is worse than a coin toss. It pointed out that this does not match
  the 0.2366 its current method is credited with, and declined to quote
  whichever figure flattered it.
- Each answer is one model call on the subscription, outside the service's
  daily budget, and recorded in `model_calls` like any other.
- The station is no longer read-only. ADR-0007's property now reads:
  read-only except for one guarded route that records a conversation and
  asks a model.
- **Not done.** Agents do not yet talk to each other this way (M64), and the
  operator's instructions are not yet routed into work (M63).
- **Not done.** Answers are not streamed: the page shows "thinking…" until the
  whole answer arrives (about half a minute on Sonnet).
