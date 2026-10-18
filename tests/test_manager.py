"""M63 — the Company Manager: the operator's one portal.

The acceptance criteria, each with a test named after it:

* the Manager's answer is read into a reply and the actions it asked for,
  and nothing it names that does not exist is acted on,
* an instruction becomes a directive every agent reads at every seat,
* a directive is withdrawn by a revoke row, never by editing one,
* the Manager can ask colleagues, by real messages each way, and reports
  back what they said,
* the Manager cannot act beyond that: no view, order, grant or mandate change,
* the Control Room opens on the Manager, and lists what the agents are told,
* only the Office's own page can post to the Manager.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.brain.briefing import briefing
from aurelis.chat.talk import thread
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.manager.directives import active, issue, revoke
from aurelis.manager.portal import MAX_ASKS, manage, manager_ref, parse
from aurelis.manager.tables import Directive
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.station.app import station_app

_NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.UTC)
_HANDLES = {"CEO", "CRITIC", "QUANT", "INTEL", "RISK"}


@pytest.fixture
def company(settings: Settings) -> Any:
    built = Runtime.build(
        settings, clock=FrozenClock(_NOW), provider=MockProvider(responder=standins())
    )
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _count(company: Runtime, sql: str) -> int:
    with company.database.session() as session:
        return int(session.execute(sa.text(sql)).scalar_one())


# ------------------------------------------------------------ reading the answer


def test_the_answer_is_read_into_a_reply_and_actions_and_nothing_invented_is_acted_on() -> None:
    plan = parse(
        "REPLY: Sure, I will.\nIt will take a day.\n"
        "DIRECTIVE: Look at Solana tokens first | TO: QUANT, NOBODY\n"
        "DIRECTIVE: Avoid big caps | TO: all\n"
        "DIRECTIVE: x\n"
        "REVOKE: DIR-0003 and dir-0004\n"
        "ASK: CRITIC: what do you think?\nASK: GHOST: are you there?\nASK: CEO: me?\n"
        "ASK: QUANT: and you?\nASK: INTEL: you?\nASK: RISK: and you?",
        _HANDLES,
    )
    assert plan.reply == "Sure, I will.\nIt will take a day."
    assert plan.directives[0] == ("Look at Solana tokens first", ("QUANT",))
    assert plan.directives[1] == ("Avoid big caps", ("all",))
    assert len(plan.directives) == 2, "too short to be an instruction"
    assert plan.revokes == ("DIR-0003", "DIR-0004")
    asked = [h for h, _ in plan.asks]
    assert "GHOST" not in asked and "CEO" not in asked
    assert asked == ["CRITIC", "QUANT", "INTEL"] and len(asked) == MAX_ASKS


# ------------------------------------------------------------ directives


def test_an_instruction_becomes_a_directive_every_seat_reads(company: Runtime) -> None:
    exchange, done = manage(company, "Focus on meme coins this week, and ask the Critic.")
    assert exchange.answer is not None and not exchange.error
    assert len(done.issued) == 1
    ref, who, text = done.issued[0]
    assert who == "everyone" and "meme-coin desk" in text
    with company.database.session() as session:
        now_on = active(session)
        brain = briefing(session).text()
    assert [d.ref for d in now_on] == [ref]
    assert "Directives:" in brain and ref in brain and text in brain
    assert "What I did:" in exchange.answer.text and ref in exchange.answer.text


def test_a_directive_is_withdrawn_by_a_revoke_row_never_by_editing_one(company: Runtime) -> None:
    with company.database.session() as session:
        boss = manager_ref(session)
        assert boss is not None
        row = issue(
            session,
            company.ledger,
            text="Prefer liquid markets",
            audience=("all",),
            manager_ref=boss,
            because="CHT-0001",
            at=_NOW,
        )
        assert revoke(
            session, company.ledger, ref=row.ref, manager_ref=boss, because="CHT-0002", at=_NOW
        )
        assert active(session) == []
        assert (
            revoke(
                session,
                company.ledger,
                ref=row.ref,
                manager_ref=boss,
                because="CHT-0003",
                at=_NOW,
            )
            is None
        ), "nothing left to withdraw"
    with company.database.session() as session, pytest.raises(sa.exc.DatabaseError):
        session.execute(sa.update(Directive).values(text="something else"))
        session.flush()
    assert _count(company, "SELECT count(*) FROM events WHERE kind = 'manager.directive_revoked'")


# ------------------------------------------------------------ consulting


def test_the_manager_asks_colleagues_by_real_messages_and_reports_back(company: Runtime) -> None:
    exchange, done = manage(company, "Focus on meme coins this week, and ask the Critic.")
    assert [h for h, _, _ in done.asked] == ["CRITIC"]
    assert "coin toss" in done.asked[0][2], "the Critic's own answer"
    assert exchange.answer is not None
    assert "I asked" in exchange.answer.text, "the report written after hearing them"
    assert _count(company, "SELECT count(*) FROM events WHERE kind = 'agent.consulted'") == 1
    with company.database.session() as session:
        kinds = [str(k) for k in session.execute(sa.text("SELECT kind FROM messages")).scalars()]
        boss = manager_ref(session)
        assert boss is not None
        assert [t.speaker for t in thread(session, boss)] == ["operator", "agent"]
    assert kinds.count("question") == 1 and kinds.count("answer") == 1


def test_the_manager_cannot_act_beyond_directives_and_questions(company: Runtime) -> None:
    tables = ("theses", "orders", "data_grants", "mandate_assessments", "mechanisms", "positions")
    before = {t: _count(company, f"SELECT count(*) FROM {t}") for t in tables}
    manage(company, "Buy a million of BTC now and turn on live trading.")
    after = {t: _count(company, f"SELECT count(*) FROM {t}") for t in tables}
    assert after == before


# ------------------------------------------------------------ the portal


def test_the_control_room_opens_on_the_manager_and_lists_the_directives(company: Runtime) -> None:
    app = station_app(company)
    said = json.loads(app.manage("Focus on meme coins this week, and ask the Critic.").body)
    assert said["answer"]["speaker"] == "agent" and said["did"]
    room = app.handle("/office/room/control", {}).body.decode()
    assert room.index("data-tab='manager'") < room.index("data-tab='company'")
    assert "data-endpoint='/office/manager'" in room
    assert "Prefer views on the meme-coin desk this week" in room, "the directives tab"
    with company.database.session() as session:
        boss = manager_ref(session)
    profile = app.handle(f"/office/agent/{boss}", {}).body.decode()
    assert "data-endpoint='/office/manager'" in profile, "clicking the Manager opens the portal"
    assert app.manage("  ").status == 400


def test_only_the_office_can_post_to_the_manager(company: Runtime) -> None:
    from aurelis.station.app import serve

    server = serve(company, port=0, background=True)
    try:
        url = f"{server.url}office/manager"
        body = json.dumps({"text": "nothing to do"}).encode()

        def post(headers: dict[str, str]) -> int:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                    return int(response.status)
            except urllib.error.HTTPError as error:
                return int(error.code)

        assert post({"Content-Type": "application/json"}) == 403
        assert post({"Content-Type": "application/json", "X-Aurelis-Office": "1"}) == 200
    finally:
        server.stop()
