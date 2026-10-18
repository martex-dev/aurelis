# ADR-0062 — The Office

Status: accepted · 2026-10-18

## Context

The operator's first idea for the interface, from Nullius, was a gamified
building where the agents live. In that idea:

- every room is a department you click into for its own dashboard;
- the agents' avatars visibly work at their posts with their names over their
  heads;
- hallways connect the rooms;
- a big central control room tells you what the whole company is doing.

Nullius built that station over M22–M35. The operator called its last
version "very close to my idea".

Aurelis never had it. Its station (M7, M36–M37, M52) is a correct, read-only
schematic: boxes in a grid, three-pixel figures, and tables. The operator's
words on 18 October were: "go back to my initial idea for the office … with
rooms and systems and meetings and avatars and everything."

## Decision

**Port the Nullius station's art and change what it is a picture of.**

- **`office/art.py`** carries Nullius's drawing code over: materials, the
  furniture placement, the side-on chamber geometry, and the figures' strides.
  Each room gets furniture for its own work: dishes and scanners in Market
  Intelligence, plot walls and scopes in Quant Research, target boards in the
  Strategy Lab, vault doors and scales in Portfolio & Risk, a big board and a
  bin bank on the Trading Floor, a reactor and coolant in the Engine Room.
- **`templates/parts.html` and `agents.html`** are copied from Nullius with
  two changes. A doorway can sit off-centre. Every figure carries the agent's
  ref, so it can be found, clicked and animated.
- **`office/map.py`** lays out the eleven rooms in three courses:
  - the five research-to-trading departments across the top;
  - Executive, the **Control Room** and Knowledge across the middle;
  - the three services along the bottom.

  `LINKS` names every hallway and lift. Every top and bottom room has a lift
  to a room in the middle course.
- **The people are the payroll.** There is one figure per employed agent, in
  its department's room. The Company Manager (CEO) works in the Control Room,
  the room the operator will talk to it from (M63). The hourly service is the
  one figure that is not a person: Nullius's servitor, in the Engine Room.
- **A figure moves only while the record says it is working.** The page
  polls `/office/live.json` every 8 seconds. That endpoint is read off the
  ledger by the existing `station/activity.py`. A working agent walks between
  its workstations with its nameplate lit. An idle one stands at its post.
  This is the rule M52 established, kept.
- **Click a room** to open its dashboard over the map (`/office/room/<id>`):
  - *the brief*: what the room is for and what happens there, in plain words;
  - *who works here*: each agent, working or at its post, and its last act;
  - *right now*: the room's lines from the live feed;
  - the station page that is about that room's work, for example voices,
    mechanisms, sealed views, the money page, the brain, the graveyard, the
    timeline or the service;
  - staff and charters.

  The heavy tabs are built only when opened (`/office/tab/<name>`). The
  mechanisms page reads the whole record and takes seconds.
- **The Control Room** shows:
  - the company's health (thinking, asleep or stopped, from ADR-0061);
  - who is working now and today's counts;
  - "ready for real money?" with the mandate's met count;
  - the path to real money;
  - the live feed;
  - a button for every room.
- **Click an agent** to open its profile over the map. M62 adds the chat.
- **The Office is the front door.** `/` serves it. The schematic facility
  moves to `/facility`, and every other page keeps its address. Room names
  are hidden on the map until you hover, as the operator asked in Nullius.
- **The health check recognises recovery.** A model answering after the
  asleep alarm reads as "thinking again" at once, rather than waiting for the
  wake that woke it to be written.

Jinja2 becomes a dependency, as in Nullius: the drawing is about 3,500 lines
of templated SVG, and porting it out of templates would only have rewritten
working art.

## Consequences

- The operator opens `localhost:8787` and sees the company as a building,
  with people who work when the record says they do.
- The figures are Nullius's eleven builds, mapped onto Aurelis roles: the
  Critic is the hooded skeptic, Risk the sealed custodian, the CEO the
  director, and so on. A new hire with an unmapped handle falls back on its
  department's figure.
- **Not done.** Each room's dashboard reuses the station's own page for its
  extra tab. They are not yet uniquely designed per department in layout and
  type, which the operator asked for in Nullius.
- **Not done.** Meetings are not yet drawn. The live company has held one
  meeting and its agents have sent each other no messages, and drawing a
  meeting that did not happen would break the station's first rule. M64 makes
  them happen, then they are drawn.
- **Not done.** The map is drawn once per page load. A new hire appears after
  a reload.
