"""The station server: read-only, loopback-bound, and built on the stdlib.

`docs/06-mission-control.md` §7 proposed FastAPI. This uses ``http.server``
instead, and the reasoning is recorded in ADR-0009. In short: the station reads
and never writes, so FastAPI's value — request validation, dependency
injection, an OpenAPI surface — applies to input handling that does not exist
here. What is left is routing a dozen GETs and holding one SSE stream open,
which the standard library does. The gain is that ``aurelis station serve``
works from a clean clone with no extras installed, and CI exercises the real
server rather than a stand-in.

**Read-only is a property of the code, not a promise.** There is no route that
accepts a POST; the handler implements ``do_GET`` and nothing else, so an
unimplemented method is a 501 from the standard library rather than a hole
somebody has to remember not to open. Write actions — opening a mission,
approving an org change — arrive with the milestones that own those decisions.

**Loopback by default.** The station exposes the whole company's internals with
no authentication, because it is a local operator tool. Binding it to a
non-loopback interface requires passing the host explicitly, and the server
says loudly what that means. A dashboard that quietly listened on 0.0.0.0 would
be publishing the research record to the network.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from aurelis.org.departments import DEPARTMENTS, Department
from aurelis.org.desks import DESKS, Desk
from aurelis.runtime import Runtime
from aurelis.station import pages
from aurelis.station import projections as proj
from aurelis.station.layout import build_facility
from aurelis.station.render import page

__all__ = ["StationServer", "serve", "station_app"]

_POLL_SECONDS = 1.0
_SSE_KEEPALIVE = 15.0


@dataclass(slots=True)
class Response:
    body: bytes
    status: int = 200
    content_type: str = "text/html; charset=utf-8"


class StationApp:
    """Routing and rendering. Framework-free, and testable without a socket."""

    __slots__ = ("runtime", "facility")

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.facility = build_facility()

    # ------------------------------------------------------------ helpers

    def _status(self, session: Any) -> proj.CompanyStatus:
        verification = self.runtime.ledger.verify(session)
        return proj.company_status(
            session,
            chain_ok=verification.ok,
            chain_detail=verification.describe(),
        )

    def _head_seq(self, session: Any) -> int:
        entries = proj.timeline(session, limit=1)
        return entries[-1].seq if entries else 0

    def _render(self, title: str, body: str | None, missing: str) -> Response:
        with self.runtime.database.session() as session:
            status = self._status(session)
            seq = self._head_seq(session)
        if body is None:
            return Response(
                page(
                    "Not found", pages.not_found(missing), status=status, seq=seq
                ).encode("utf-8"),
                status=404,
            )
        return Response(page(title, body, status=status, seq=seq).encode("utf-8"))

    # ------------------------------------------------------------- routing

    def handle(self, path: str, query: dict[str, list[str]]) -> Response:
        """Resolve one GET. Pure apart from reading the database."""
        parts = [unquote(part) for part in path.strip("/").split("/") if part]

        if not parts:
            with self.runtime.database.session() as session:
                body = pages.facility_page(session, self.facility)
            return self._render("Facility", body, "")

        head, rest = parts[0], parts[1:]
        handler = _ROUTES.get(head)
        if handler is None:
            return self._render("Not found", None, f"/{path.strip('/')}")
        return handler(self, rest, query)

    # -------------------------------------------------------------- views

    def _timeline(self, _rest: list[str], query: dict[str, list[str]]) -> Response:
        limit = _int(query.get("limit"), 200)
        with self.runtime.database.session() as session:
            body = pages.timeline_page(session, limit=limit)
        return self._render("Timeline", body, "")

    def _department(self, rest: list[str], _q: dict[str, list[str]]) -> Response:
        department = _enum(Department, rest)
        if department is None or department not in DEPARTMENTS:
            return self._render("Not found", None, f"department {rest}")
        with self.runtime.database.session() as session:
            body = pages.department_page(session, department)
        return self._render(DEPARTMENTS[department].name, body, "")

    def _agent(self, rest: list[str], _q: dict[str, list[str]]) -> Response:
        if not rest:
            with self.runtime.database.session() as session:
                return self._render("Staff", pages.agents_page(session), "")
        with self.runtime.database.session() as session:
            body = pages.agent_page(session, rest[0])
        return self._render(rest[0], body, f"agent {rest[0]}")

    def _agents(self, _rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            return self._render("Staff", pages.agents_page(session), "")

    def _mission(self, rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            if not rest:
                return self._render("Missions", pages.missions_page(session), "")
            body = pages.mission_page(session, rest[0])
        return self._render(rest[0], body, f"mission {rest[0]}")

    def _missions(self, _rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            return self._render("Missions", pages.missions_page(session), "")

    def _meeting(self, rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            if not rest:
                return self._render("Meetings", pages.meetings_page(session), "")
            body = pages.meeting_page(session, rest[0])
        return self._render(rest[0], body, f"meeting {rest[0]}")

    def _meetings(self, _rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            return self._render("Meetings", pages.meetings_page(session), "")

    def _hypothesis(self, rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            if not rest:
                return self._render("Research", pages.research_page(session), "")
            body = pages.hypothesis_page(session, rest[0])
        return self._render(rest[0], body, f"hypothesis {rest[0]}")

    def _research(self, _rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            return self._render("Research", pages.research_page(session), "")

    def _desk(self, rest: list[str], _q: dict[str, list[str]]) -> Response:
        desk = _enum(Desk, rest)
        if desk is None or desk not in DESKS:
            return self._render("Not found", None, f"desk {rest}")
        with self.runtime.database.session() as session:
            body = pages.desk_page(session, desk)
        return self._render(DESKS[desk].name, body, "")

    def _floor(self, _rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            return self._render("The Floor", pages.floor_page(session), "")

    def _graveyard(self, _rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            return self._render("Graveyard", pages.graveyard_page(session), "")

    def _knowledge(self, _rest: list[str], _q: dict[str, list[str]]) -> Response:
        with self.runtime.database.session() as session:
            return self._render("Knowledge", pages.knowledge_page(session), "")

    def _room(self, rest: list[str], _q: dict[str, list[str]]) -> Response:
        room = self.facility.room(rest[0]) if rest else None
        if room is None:
            return self._render("Not found", None, f"room {rest}")
        return self._render(
            room.title, pages.sealed_room_page(room.room_id, room.title, room.owns), ""
        )

    # ---------------------------------------------------------------- data

    def events_since(self, since: int) -> list[dict[str, Any]]:
        """New ledger entries, for the SSE stream."""
        with self.runtime.database.session() as session:
            entries = proj.timeline(session, since=since)
        return [
            {
                "seq": entry.seq,
                "at": entry.at.strftime("%m-%d %H:%M"),
                "actor": entry.actor,
                "kind": entry.kind,
                "subject": entry.subject,
            }
            for entry in entries
        ]


Route = Callable[[StationApp, list[str], dict[str, list[str]]], Response]

_ROUTES: dict[str, Route] = {
    "timeline": StationApp._timeline,
    "department": StationApp._department,
    "agent": StationApp._agent,
    "agents": StationApp._agents,
    "mission": StationApp._mission,
    "missions": StationApp._missions,
    "meeting": StationApp._meeting,
    "meetings": StationApp._meetings,
    "hypothesis": StationApp._hypothesis,
    "research": StationApp._research,
    "desk": StationApp._desk,
    "floor": StationApp._floor,
    "graveyard": StationApp._graveyard,
    "knowledge": StationApp._knowledge,
    "room": StationApp._room,
}


def station_app(runtime: Runtime) -> StationApp:
    return StationApp(runtime)


class _Handler(BaseHTTPRequestHandler):
    """GET only. Every other verb is a 501 from the standard library."""

    server_version = "AurelisStation"
    protocol_version = "HTTP/1.1"
    app: StationApp

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence per-request logging.

        The ledger is the company's record; a second, unstructured one on
        stderr competes with it and tells an operator nothing they cannot get
        from the timeline.
        """

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's spelling
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/events":
            self._stream(_int(query.get("since"), 0))
            return

        try:
            response = self.app.handle(parsed.path, query)
        except Exception as error:  # noqa: BLE001 - a 500 is better than a hang
            body = (
                "<h1>Station error</h1><p class='nodata'>"
                f"{type(error).__name__}: {error}</p>"
            ).encode()
            response = Response(body, status=500)

        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)

    def _stream(self, since: int) -> None:
        """Server-sent events on ledger append.

        Polls rather than subscribes. The ledger is a table with a monotonic
        sequence, so "what is new?" is one indexed query, and a polling reader
        cannot miss an append the way a listener that reconnects can.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        cursor = since
        last_ping = time.monotonic()
        try:
            while True:
                entries = self.app.events_since(cursor)
                if entries:
                    cursor = int(entries[-1]["seq"])
                    payload = json.dumps({"entries": entries})
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    last_ping = time.monotonic()
                elif time.monotonic() - last_ping > _SSE_KEEPALIVE:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_ping = time.monotonic()
                time.sleep(_POLL_SECONDS)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


@dataclass(slots=True)
class StationServer:
    """A running station. Start it, read ``url``, stop it."""

    httpd: ThreadingHTTPServer
    thread: threading.Thread
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def serve(
    runtime: Runtime,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    background: bool = False,
) -> StationServer:
    """Start the station.

    ``host`` defaults to loopback and should stay there. The station shows
    every meeting, every agent's permissions and every unpublished result with
    no authentication at all, because it is an operator's local window into
    their own workspace. Exposing it to a network publishes the research record.
    """
    handler = type("_BoundHandler", (_Handler,), {"app": station_app(runtime)})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True

    thread = threading.Thread(target=httpd.serve_forever, name="aurelis-station")
    thread.daemon = True
    thread.start()

    server = StationServer(httpd, thread, host, httpd.server_address[1])
    if not background:
        try:
            thread.join()
        except KeyboardInterrupt:
            server.stop()
    return server


def _int(values: list[str] | None, default: int) -> int:
    if not values:
        return default
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return default


def _enum(kind: Any, rest: list[str]) -> Any:
    if not rest:
        return None
    try:
        return kind(rest[0])
    except ValueError:
        return None
