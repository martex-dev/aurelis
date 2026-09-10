# ADR-0029 — A view is attacked before it is sealed, and the attacker is scored

Status: accepted · 2026-09-10

## Context

M25's first seven views on a real model all said *down*. Seven agents with
different charters read the same twenty-four closes and reached the same
conclusion in different words. Putting each agent's identity in the prompt
made them distinguishable and did not make them independent. The brief is
explicit about the missing piece: adversarial agents whose job is to destroy a
promising view, a critic scored on false discoveries caught rather than on
agreeableness, and the rule that a thesis nobody attacked has not been tested.

The company already has the shape of this at the research level — M5's
critic raises objections with discriminating tests, and M14 seats an agent as
that critic and scores it on planted defects. Neither touches a forward view,
which resolves in a day and has no mechanical test to dispatch. What a view
needs is an adversary in the loop before the seal, and a score afterwards.

## Decision

### Before a view is sealed, a different agent attacks it

After the author's view is parsed, figure-checked and found forward, and
before anything is written, an agent holding the critic or adversarial charter
— never the author — is shown the same material and the proposed view, and
replies with a verdict (`stands`, `weakened`, `broken`) and the strongest
reason the view is wrong. The attack is held to the figure rule. The author
then sees the attack and replies `hold`, `revise` with a new confidence, or
`withdraw`.

Everything is sealed together: who attacked, the verdict, the attack, the
confidence stated before it, the response and its reason, and the confidence
after. The seal hashes all of it; the immutability trigger covers the new
columns; a withdrawal is a decline on the ledger carrying the attack. The
Brier score is computed on the confidence *after* the attack, because that is
the view the company holds.

### The critic is scored on whether its verdicts predicted failure

When the horizon expires: a `broken` on a view that turned out wrong is a
catch, a `broken` on a view that turned out right is a false alarm, a `stands`
on a view that turned out wrong is a miss. Precision and catch rate are
reported side by side, per critic, on the agent's page and in the calibration
report. A critic that says `broken` to everything catches everything, and its
false-alarm count says what that is worth.

### An unreadable attack does not block the seal

The critic's failure is recorded against the critic — verdict `unreadable`,
the reason in the attack column — and the view is sealed as the author stated
it. The author's view is not hostage to the critic's form. A view sealed with
no critic available says so on its page rather than implying a review.

## Consequences

- **Four model calls per view where there were two.** Choose, view, attack,
  respond. The agenda's estimate moved from two to four, and the loop stops
  before the budget as before.

- **The stand-in adversary has one policy** — anything above 0.6 is broken —
  and the stand-in author revises to 0.55 when told so. That is enough to
  exercise the seal, the response and the scoring offline, and it is not
  judgement. On the offline company every view now seals at 0.55, which is a
  fact about the two stand-ins agreeing with each other.

- **The critic of the critic is not built.** Whether the adversary is itself
  reasoning or reflexively saying `broken` is what its false-alarm count will
  show over time; nothing yet gives more budget to a critic with a good
  record or retires one with a bad one.

- **The attack reads the same twenty-four closes the author did.** It can
  attack the reasoning, not the evidence. Independence of evidence is the
  event and entity layer, still not built.
