"""The shared brain: one memory every agent reads, and every agent can add to.

Through M45 each agent saw only its own record: its last five scored views and
its own calibration. What the others had concluded -- which mechanisms died and
why, which patterns eight colleagues had already declined, what the operator
thinks the opportunity is -- reached nobody. A society whose members cannot
hear each other is a set of strangers.

The brain has three parts, and the split is the design:

* **The record's own summary** (:mod:`aurelis.brain.briefing`): mechanisms
  under test and their verdicts, the retired ones and the reason, the patterns
  most often declined, the company's calibration, the paper book. Derived
  deterministically from the database on every read. Its figures are the
  record's, so an agent may cite them.
* **Notes** (:mod:`aurelis.brain.notes`): one line an agent chose to leave for
  the company when it answered a seat, or a note the operator dropped into the
  vault's inbox. Attributed, timestamped, append-only. Opinions, not evidence:
  their figures may not be cited.
* **The vault** (:mod:`aurelis.brain.vault`): all of it rendered as an Obsidian
  vault the operator can open, with a page per mechanism, agent, note and
  instrument, linked. The database remains the record; the vault is a view of
  it, except its ``Inbox`` folder, which is how the operator writes in.
"""
