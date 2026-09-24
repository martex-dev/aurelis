"""M46 — the shared brain: one memory every agent reads, and can add to.

The acceptance criteria, each with a test named after it:

* an agent leaves a note with its view, and the next agent to sit reads it
  in its system prompt and, on that instrument, beside its material,
* a note citing a figure the agent was not shown is dropped and the view it
  came with still stands,
* an agent that declines a pattern at the discovery seat can leave a note on
  those events, and the record part of the brain lists the mechanisms, the
  retired ones with their reason, and the patterns most declined,
* the brain is rendered as an Obsidian vault with a page per mechanism, agent,
  note and instrument, linked; an unchanged page is not rewritten and a stale
  generated page is removed,
* an operator note dropped in the vault's inbox is read into the brain with
  its links and tags as topics, attributed to the operator, and moved,
* a note is append-only,
* every wake syncs the brain and says so,
* the CLI and the station show the brain, and the operator can add a note
  from the CLI.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from aurelis.brain.briefing import briefing, company_brief
from aurelis.brain.notes import OPERATOR, recent_notes
from aurelis.brain.tables import BrainNote
from aurelis.brain.vault import render_brain, sync_brain
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import EventKind
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.seat import seat_agent
from aurelis.judgement.standin import scripted_judge
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.station.app import station_app

_HOUR = 3600
_START = 1_780_000_000
_NOTE = "The close has printed a new high on nearly every bar; nobody has sold into it yet."


def _climbing(count: int) -> bytes:
    rows = [
        [_START + i * _HOUR, 99.0 + i, 101.0 + i, 100.0 + i, 100.0 + i, 5.0] for i in range(count)
    ]
    return json.dumps(list(reversed(rows))).encode()


class _Payload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._data)


class _Recorder:
    """A responder that adds a NOTE to views and keeps every prompt it saw."""

    def __init__(self, note: str = _NOTE) -> None:
        self.note = note
        self.seen: list[LlmRequest] = []

    def __call__(self, request: LlmRequest) -> str:
        self.seen.append(request)
        reply = standins()(request)
        if "State your view on" in request.messages[-1].content and self.note:
            reply = scripted_judge(request) + f"NOTE: {self.note}\n"
        return reply


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 199 * _HOUR + 600, tz=dt.UTC))


def _company(settings: Settings, clock: FrozenClock, responder: Any) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=responder))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_climbing(200)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
    return built


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def company(settings: Settings, clock: FrozenClock, recorder: _Recorder) -> Any:
    built = _company(settings, clock, recorder)
    try:
        yield built
    finally:
        built.close()


# ------------------------------------------------------------ notes at the seat


def test_an_agent_leaves_a_note_with_its_view_and_the_next_agent_reads_it(
    company: Runtime, recorder: _Recorder
) -> None:
    first = seat_agent(company, agent_handle="INTEL")
    assert first is not None
    with company.database.session() as session:
        notes = recent_notes(session)
        author = company.roster.by_handle(session, "INTEL").ref
        noted = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = :k"),
            {"k": EventKind.BRAIN_NOTED.value},
        ).scalar_one()
    assert len(notes) == 1 and notes[0].text == _NOTE
    assert notes[0].author == author and notes[0].topics == ["BTC-USD"]
    assert notes[0].source_ref == first.ref and noted == 1

    recorder.seen.clear()
    recorder.note = ""
    seat_agent(company, agent_handle="QUANT")  # a different agent, so BTC is offered
    systems = [r.system for r in recorder.seen]
    assert systems and all("SHARED BRAIN" in s and _NOTE in s for s in systems)
    view = next(r for r in recorder.seen if "State your view on" in r.messages[-1].content)
    assert "Shared brain, notes on BTC-USD" in view.messages[-1].content
    assert _NOTE in view.messages[-1].content


def test_a_note_citing_a_figure_it_was_not_shown_is_dropped_and_the_view_stands(
    settings: Settings, clock: FrozenClock
) -> None:
    built = _company(settings, clock, _Recorder("Expect another 42.7 percent before Friday."))
    try:
        sealed = seat_agent(built, agent_handle="INTEL")
        with built.database.session() as session:
            notes = recent_notes(session)
    finally:
        built.close()
    assert sealed is not None, "the view stands"
    assert notes == [], "a figure nobody measured does not reach every other agent"


# ------------------------------------------------------------ the record part


def test_a_decline_at_discovery_leaves_a_note_and_the_record_lists_mechanisms_retirements_and_declines(  # noqa: E501
    company: Runtime,
) -> None:
    from aurelis.mechanism.discovery import propose_mechanism

    with company.database.session() as session:
        for bar in (120, 140, 160):
            for kind, hour in (("price.volume_spike", bar), ("price.range_break", bar + 2)):
                company.world.record(
                    session,
                    kind=kind,
                    at=dt.datetime.fromtimestamp(_START + hour * _HOUR, tz=dt.UTC),
                    entity_kind="instrument",
                    entity_key="BTC-USD",
                    payload={"bar": hour},
                    source="test",
                )

    class _Declines:
        name = "mock"

        def complete(self, session: Any, request: LlmRequest) -> Any:  # noqa: ARG002
            return MockProvider(
                responder=lambda _r: (
                    "MECHANISM: nothing\n"
                    "BECAUSE: a spike before a break is one move seen twice.\n"
                    "NOTE: Spikes and breaks on the same bar are the same event; "
                    "do not pair them.\n"
                )
            ).complete(request)

    with company.database.session() as session:
        for handle in ("QUANT", "INTEL"):
            declined = propose_mechanism(
                _Declines(),
                session,
                company.mechanisms,
                agent_ref=company.roster.by_handle(session, handle).ref,
                trigger_kind="price.volume_spike",
                second_kind="price.range_break",
                ledger=company.ledger,
            )
            assert declined is None
        stated = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="a new high draws buyers",
            trigger_kind="price.range_break",
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.6"),
            why="a new high draws in the momentum buyers who were waiting for it.",
            other_side="the shorts who sold the old high and now cover.",
            decay="it fades as the crowd learns to buy the high, within months.",
            origin="invented",
            found_on_instrument="BTC-USD",
            found_on_event="none",
            model="test",
        )
        dead = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "INTEL").ref,
            title="spikes fade",
            trigger_kind="price.volume_spike",
            desk="crypto",
            horizon_hours=24,
            direction="down",
            confidence=Decimal("0.55"),
            why="a spike is forced flow that is done as soon as it prints.",
            other_side="the late buyers who chase the spike.",
            decay="it is well known and crowds within weeks.",
            origin="invented",
            found_on_instrument="BTC-USD",
            found_on_event="none",
            model="test",
        )
        company.mechanisms.retire(
            session, dead.ref, reason="did not beat the drift over enough episodes"
        )
        notes = recent_notes(session)
        record = company_brief(session)
    same = "Spikes and breaks on the same bar are the same event; do not pair them."
    assert [n.text for n in notes] == [same, same], "two agents said it: two notes, two authors"
    assert len({n.author for n in notes}) == 2
    assert {"price.volume_spike", "price.range_break", "BTC-USD"} <= set(notes[0].topics)
    assert stated.ref in record and "Mechanisms under test" in record
    assert dead.ref in record and "did not beat the drift" in record
    assert "price.volume_spike then price.range_break (2 declines)" in record
    assert "one move seen twice" in record


# ------------------------------------------------------------ the vault


def test_the_brain_is_an_obsidian_vault_with_a_page_per_mechanism_agent_note_and_instrument(
    company: Runtime, tmp_path: Path
) -> None:
    seat_agent(company, agent_handle="INTEL")
    with company.database.session() as session:
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="a new high draws buyers",
            trigger_kind="price.range_break",
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.6"),
            why="a new high draws in the momentum buyers who were waiting for it.",
            other_side="the shorts who sold the old high and now cover.",
            decay="it fades as the crowd learns to buy the high, within months.",
            origin="invented",
            found_on_instrument="BTC-USD",
            found_on_event="none",
            model="test",
        )
        author = company.roster.by_handle(session, "INTEL").ref
    root = tmp_path / "vault"
    (root / "Mechanisms").mkdir(parents=True)
    (root / "Mechanisms" / "MEC-9999.md").write_text("stale", encoding="utf-8")
    at = company.clock.now()
    with company.database.session() as session:
        first = render_brain(session, root, at=at)
        again = render_brain(session, root, at=at)
    home = (root / "Home.md").read_text(encoding="utf-8")
    assert f"[[{mechanism.ref}]]" in home and _NOTE in home
    page = (root / "Mechanisms" / f"{mechanism.ref}.md").read_text(encoding="utf-8")
    assert page.startswith("---\n") and f'ref: "{mechanism.ref}"' in page
    assert "## Who is on the other side" in page
    agent = (root / "Agents" / f"{author}.md").read_text(encoding="utf-8")
    assert 'aliases: ["INTEL"]' in agent and "Notes left for the company" in agent
    assert (root / "Notes" / "NOTE-0001.md").exists()
    assert _NOTE in (root / "Instruments" / "BTC-USD.md").read_text(encoding="utf-8")
    assert (root / "Inbox" / "README.md").exists()
    assert first.removed == 1 and not (root / "Mechanisms" / "MEC-9999.md").exists()
    assert again.written == 0 and again.unchanged == first.written + first.unchanged


def test_an_operator_note_dropped_in_the_inbox_is_read_into_the_brain_and_moved(
    company: Runtime, tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    (root / "Inbox").mkdir(parents=True)
    (root / "Inbox" / "idea.md").write_text(
        "Watch [[BTC-USD]] around the funding reset; memecoins run on #solana weekends.",
        encoding="utf-8",
    )
    export = sync_brain(company, root=root)
    assert len(export.ingested) == 1 and "1 operator note(s) read" in export.describe()
    with company.database.session() as session:
        note = recent_notes(session)[0]
        seen = briefing(session, topics=("BTC-USD",))
    assert note.author == OPERATOR and note.kind == "operator"
    assert set(note.topics) == {"BTC-USD", "solana"}
    assert "Watch BTC-USD around the funding reset" in note.text
    assert not (root / "Inbox" / "idea.md").exists()
    read = list((root / "Inbox" / "Read").glob("*idea.md"))
    assert len(read) == 1 and note.ref in read[0].name
    assert "from the operator" in seen.notes
    assert sync_brain(company, root=root).ingested == (), "never read twice"


def test_a_note_is_append_only(company: Runtime) -> None:
    seat_agent(company, agent_handle="INTEL")
    engine = company.database.engine
    with pytest.raises(sa.exc.IntegrityError, match="append-only"), engine.begin() as connection:
        connection.execute(sa.update(BrainNote).values(text="something else entirely"))
    with pytest.raises(sa.exc.IntegrityError, match="append-only"), engine.begin() as connection:
        connection.execute(sa.delete(BrainNote))


# ------------------------------------------------------------ the wake, the CLI, the station


def test_every_wake_syncs_the_brain_and_says_so(company: Runtime, tmp_path: Path) -> None:
    root = tmp_path / "vault"
    wake = cycle_once(
        company, service=Service(company, calls_per_day=0, cycles_per_wake=1, brain_root=root)
    )
    assert "brain:" in wake.note and "page(s) written" in wake.note
    assert (root / "Home.md").exists()


def test_the_cli_and_the_station_show_the_brain_and_the_operator_can_add_a_note(
    company: Runtime, settings: Settings
) -> None:
    from aurelis.cli.main import app

    workspace = str(settings.home)
    added = CliRunner().invoke(
        app,
        [
            "brain",
            "note",
            "Memecoins that trend on two chains at once are worth a look.",
            "-w",
            workspace,
            "--topic",
            "memecoin",
        ],
    )
    assert added.exit_code == 0, added.output
    assert "added to the shared brain" in added.output
    shown = CliRunner().invoke(app, ["brain", "show", "-w", workspace])
    assert shown.exit_code == 0 and "worth a look" in shown.output
    listed = CliRunner().invoke(app, ["brain", "notes", "-w", workspace])
    assert listed.exit_code == 0 and "operator" in listed.output
    page = station_app(company).handle("/brain", {}).body.decode()
    assert "Shared brain" in page and "worth a look" in page and "OPERATOR" in page
