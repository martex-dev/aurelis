# ADR-0038 — The facility in pixels

Status: accepted · 2026-09-11

## Context

The brief asks for a pixel-art research facility, game-like without being
childish, and names the station the primary human interface. `CLAUDE.md` §34
forbids decoration that pretends to be instrumentation and dashboards that
look busy whatever the record says. The M7 facility was a cutaway building
drawn in vectors with blocky staff; honest, and flat. A pixel-art pass that
added scenery would have violated §34 on its first sprite.

## Decision

### One rule: a pixel carries identity, measured state, or nothing

- **Identity.** Every agent has an avatar: an eight-by-eight sprite mirrored
  so it reads as a face, drawn from the SHA-256 of the agent's reference. The
  same agent is the same sprite on every page and every build. It is
  coloured by state — lit when working, unlit when not — and it wears on the
  agent's page and beside "stated by" on a mechanism's page.

- **Measured state.** A room's ceiling LED blinks only when the room is
  working; its staff sprites move, in two stepped frames, only when they are.
  A mechanism that is gathering evidence shows a bar whose width is
  `scored / 20`, with the two numbers printed beside it, because a bar
  without its numbers is a mood. The bar clamps at full and still prints
  `25/20`; with nothing to measure it draws nothing.

- **Nothing.** Floor tiles every eight pixels, a scanline overlay on the
  shell, crisp edges on every rectangle, a blocky mark before the brand.
  Structure, and none of it carries a reading — the same standard the pipes
  and consoles have met since M7.

### No assets

Everything is generated geometry and CSS. The sealed build is still one file
that fetches nothing, the label-overlap check still runs over the same
labels, and a diff of two renders still shows what changed in the company.

## Consequences

- **A still room is a true still room.** On the live workspace between
  wakes nothing blinks and nobody moves: every agent is active and none is
  working, because the service is asleep until the hour. The two mechanism
  rows show `1/20` at five percent. A facility that animated itself to look
  alive would have been the failure §34 names; this one is still because
  the company is.

- **Not done.** The brief's full facility — clickable rooms with interior
  views, agents walking corridors between rooms as their tasks move, a
  company timeline as a ticker — is further work under the same rule. The
  monospace face is still the system's; a bitmap font would need an asset
  the station has decided not to carry.
