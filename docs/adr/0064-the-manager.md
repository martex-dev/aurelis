# ADR-0064 — The Manager: the operator's one portal

Status: accepted · 2026-10-18

## Context

The operator asked for one agent that controls, manages, monitors, instructs
and watches over every other agent, and is "the one big portal that I talk
with". M62 let the operator talk to any agent, but talking changes nothing:
an agent cannot act from a conversation. Nor did the company have any way to
turn a person's wish into different work. It chooses its own work from the
mandate (ADR-0025), and its agents had sent each other no messages.

## Decision

**The Company Manager (the CEO charter) sits in the Control Room and is the
operator's portal.** The Control Room opens on a conversation with it, and
so do the "talk to the Manager" button in the top bar and a click on its
avatar. It answers from the whole company's situation:

- health;
- the mandate verdict;
- the data grants, and the desks that have no feed;
- the active directives;
- every agent's last act;
- the shared brain;
- the conversation so far.

It may do three things besides talking, each as a line after its reply:

1. **`DIRECTIVE: … | TO: all` (or handles).** This is a standing instruction,
   kept in the append-only `directives` table. Every active directive is
   added to the shared brain's briefing, so every agent reads it at every
   seat, together with a rule telling the agent to let directives steer what
   it looks at, never what it believes or which figures it cites. This is how
   an instruction becomes work: the agents' choices change at their next seat.
   No new code path is needed for each wish.
2. **`REVOKE: DIR-…`.** This withdraws a directive. A revoke is a new row,
   and the trigger refuses edits and deletes.
3. **`ASK: HANDLE: …`.** This puts a question to a colleague, up to three per
   message. The question and the answer are real messages (`comms.post`,
   QUESTION from the Manager, ANSWER from the colleague). These are the first
   messages the live company's agents have sent each other. The colleague
   answers from its own seat. The Manager is then shown the answers and
   writes its report.

The reply that is stored ends with "What I did", which lists the directives
issued, the directives withdrawn and the questions asked. The ledger records
`manager.directive_issued`, `manager.directive_revoked` and
`manager.consulted`.

**What the Manager cannot do, by construction, not just by instruction.** It
has no path to an order, a grant, a budget, a Risk limit or the mandate. A
test asserts none of those tables move when the operator asks it to buy and
to go live. Its prompt also says so, and tells it to say what is missing:
for example, that a market has no data feed and needs the operator to grant
one.

Unknown handles in its output are dropped, never guessed at. A directive
with no known audience goes to everyone. A directive shorter than four
characters is not an instruction.

## Consequences

- The operator can steer the whole company in one sentence, and see exactly
  what the company was told and when (the *directives* tab).
- A message that makes the Manager consult colleagues costs 2 + N model
  calls, with N at most 3. The Manager is on the high tier, so it uses Opus.
  This can take minutes.
- Directives steer choices. They do not create capabilities. "Trade forex"
  has no effect until a forex feed exists, and the Manager says so.
- **Not done.** Directives are not yet scored. Nothing measures whether the
  company did better while one was active, which is the evidence for keeping
  or withdrawing it.
- **Not done.** Directives do not expire on their own; the Manager withdraws
  one when asked.
- **Not done.** The brain vault (Obsidian) does not yet render directives on
  its own page; they appear in every seat's briefing and in the Office.
- **Not done.** Agents still do not start conversations with each other
  unprompted. M64 makes collaboration part of their own work.
