# ADR-0065 — The agents work together

Status: accepted · 2026-10-18

## Context

The operator's idea was agents "working together not like BUT EXACTLY like
real humans": a trader asks the news analysts and they hand over what they
have, specialists combine what they know, disagreements get talked out.

The live company's record said otherwise. It had held one meeting in its
whole life, and its agents had sent each other no messages. Each agent worked
alone, and the only thing they shared was the brain (M46). The meeting
machinery from M3 existed but was never part of their own work. The
Manager's consultations (M63) were the first messages, and those happen only
when the operator asks.

## Decision

Collaboration becomes part of the agents' own work, in two places, both
bounded, both recorded, and one measured.

**1. Asking for help while working (`collab/consult.py`).**

- Any agent stating a view is told whom it may ask: every colleague, by
  handle and department.
- It may reply `ASK: HANDLE: question` instead of a view, once.
- The colleague answers from its own seat: identity, method, brain, its own
  record, and the brain's notes on that market.
- The question and the answer are real messages (QUESTION and ANSWER), and
  the exchange is an `agent.consulted` event.
- The asker is then shown the answer, labelled an opinion like a note, and
  states its view or declines. It may not ask again.
- A figure that appears only in the answer is not citable. The figure guard
  is computed from the original material, and the answer is not added to it.
- Not asking costs nothing extra. Asking costs two calls.
- The consultation runs inside the seat's own database session, because the
  seat is already inside a write and SQLite has one writer. The tests caught
  this as `database is locked`.
- The Manager's consultations (M63) now use the same code.

**2. Huddles on disagreements (`collab/huddle.py`).**

- **When.** Two agents hold opposite open views (one sealed *up*, the other
  *down*) on the same market.
- **Who.** The two agents, chaired by a moderator who holds neither view: the
  Critic, or the Lead Researcher when the Critic is one of the two.
- **How.** Five model calls, in this order:
  - each makes its case;
  - each answers the other and states a revised probability that the market
    is up at its own view's horizon;
  - the moderator writes the company's position (up, down or none) and one
    line for the shared brain.
- **Records.** Each turn is a `meeting_turns` row, the position a `decisions`
  row holding both agents' before and after probabilities, and the line a
  brain note. The meeting is `productive` because of what it changed.
- **Limits.** At most 2 huddles per wake and 6 per day, never two on one
  market in a day, and only while the wake's call budget allows. The service
  holds them after the daily duties.
- **What it does not change.** The sealed views stand. Nothing said in a
  huddle edits the record of what was believed before it.

**3. Whether talking helps is measured.** `huddle_record` scores, once views
resolve, the probability each agent held before the huddle (its sealed view)
and the one it gave after, against what happened. The Control Room's
*working together* tab shows the two Brier scores, every huddle, and who
asked whom. Until ten such views have resolved it says there are too few to
tell.

## Consequences

- Every seat's prompt now lists the colleagues it may ask: about a hundred
  tokens per view.
- A huddle costs five calls. On a day with many disagreements, huddles
  compete with views for the budget, which is why they are capped.
- If agents turn out worse calibrated after talking, the record will say so,
  and the company should hold fewer huddles. CLAUDE.md §16 says not to assume
  that more agents or more meetings make the company smarter. This is the
  first place the company tests that about itself.
- **Not done.** Agents cannot yet ask more than one colleague, or ask a
  follow-up.
- **Not done.** Huddles are not drawn as people gathering on the map. The
  station shows them in the feed and the Control Room.
- **Not done.** Only opposite views trigger a meeting. Other occasions are
  not yet covered: a mechanism about to be decided, a scheme losing money, a
  directive that conflicts with the record.
