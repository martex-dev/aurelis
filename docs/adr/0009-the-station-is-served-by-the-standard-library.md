# ADR-0009 — The station is served by the standard library

Status: accepted · 2026-09-05
Amends: `docs/06-mission-control.md` §7, which proposed FastAPI
Implements: `CLAUDE.md` §19, §28, §29

## Context

`docs/06-mission-control.md` §7 was written before the station existed and
listed FastAPI over read-only projections, SSE for push, and server-generated
SVG with a light interactive shell. `CLAUDE.md` §29 asks that technology be
chosen after auditing what is actually needed rather than assumed up front, and
§28 warns against introducing machinery for appearance.

Having built the projections, the shape of the thing is clear:

- Thirteen GET routes.
- One SSE stream that polls a monotonic sequence column.
- No request body, anywhere. Nothing is parsed except a path and two integers.
- No authentication, because it is a local operator tool bound to loopback.

FastAPI's value is concentrated in request validation, dependency injection,
async I/O and a generated OpenAPI surface. Three of those apply to input
handling the station does not do, and the fourth matters for an API other
programs call — which this is not; the consumer is a browser rendering HTML the
server produced.

Against that, adding it costs a dependency tree (Starlette, Pydantic already
present, plus an ASGI server) that must be installed before `aurelis station
serve` works at all.

## Decision

**The station is served by `http.server.ThreadingHTTPServer`.** No web
framework, no ASGI server, no new dependency.

- `StationApp` holds routing and rendering and takes no socket, so every route
  is testable by calling a method.
- `_Handler` implements `do_GET` and nothing else.
- SSE is a long-lived response that polls `events.seq` and writes
  `data: {...}` frames.
- The server binds `127.0.0.1` unless a host is passed explicitly, and says
  what a non-loopback bind means when one is.

## Rationale

**Read-only becomes structural.** A framework makes adding a POST route a
one-line change. Here, the absence of `do_POST` means an unimplemented method
returns 501 from the standard library. The station cannot write to the record
because there is no code path through which it could, not because nobody has
added one yet.

**`aurelis station serve` works from a clean clone.** No extras, no
`pip install` step between cloning and seeing the company. For a tool whose
entire purpose is that a human can operate the system without opening a
terminal, an installation prerequisite is a bad first instruction.

**CI exercises the real server.** `test_the_server_starts_and_answers` opens an
actual socket and fetches an actual page on every matrix job, because the
server needs nothing that CI would otherwise skip.

**The workload does not justify async.** The station is a handful of indexed
SQLite reads per page against a WAL-mode database that does not block readers.
Threads are sufficient and are what SQLAlchemy's synchronous session wants.

## Consequences

- Routing is a dict of prefixes rather than decorators. It is less elegant and
  fits on one screen.
- No OpenAPI document. Nothing consumes one; if a programmatic API is ever
  wanted, it is a separate decision with its own ADR.
- SSE polls at one second rather than being pushed. The ledger is a table with
  a monotonic sequence, so a polling reader cannot miss an append the way a
  listener that reconnects can — this is a robustness gain, not only a
  simplification.
- If write actions arrive (opening a mission from the station, approving an org
  change), the input-validation argument changes and this decision should be
  revisited. That is the trigger to look at it again, and it is written here so
  the revisit is deliberate rather than incidental.

## Alternatives considered

**FastAPI, as originally proposed.** Rejected on the reasoning above. Worth
revisiting the moment the station accepts input.

**Flask.** Smaller than FastAPI and still a dependency, for routing that is
thirteen entries in a dict.

**A static build only, with no server.** Rejected: the sealed snapshot exists
and is the right artifact for citation, but it cannot show what is happening
now, and `CLAUDE.md` §19 wants a live window into the organisation.
