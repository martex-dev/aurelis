"""M62 — click any agent in the Office and talk to it.

The acceptance criteria, each with a test named after it:

* the operator's line and the agent's answer are both kept on the record,
  append-only, with a ledger event each,
* the agent answers as itself: its identity and method, the shared brain, its
  own record and the conversation so far are in what it is shown,
* figures it was not shown are flagged beside the answer, not refused,
* when it cannot answer, what the operator said is still on the record and
  the reason is given,
* a conversation cannot act: no view, order or note comes out of it,
* the Office opens an agent on a conversation with it,
* only the Office's own page can post: another site in the same browser
  cannot.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.chat.tables import ChatTurn
from aurelis.chat.talk import ask, thread
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.errors import ProviderUnavailable
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.station.app import station_app

_NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.UTC)


class _Ear:
    """A provider that remembers what each seat was shown."""

    name = "mock"

    def __init__(self, reply: str = "") -> None:
        self.inner = MockProvider(responder=standins())
        self.seen: list[Any] = []
        self.reply = reply
        self.down = False

    def complete(self, request: Any) -> Any:
        if self.down:
            raise ProviderUnavailable("allowance is exhausted; resets 5am")
        self.seen.append(request)
        if self.reply and "Answer the operator as" in request.messages[-1].content:
            from aurelis.platform.llm.providers import MockProvider as M

            return M(responder=lambda _r: self.reply).complete(request)
        return self.inner.complete(request)

    def availability(self) -> Any:
        from aurelis.platform.llm.providers import Availability

        return Availability("mock", True, "")


@pytest.fixture
def ear() -> _Ear:
    return _Ear()


@pytest.fixture
def company(settings: Settings, ear: _Ear) -> Any:
    built = Runtime.build(settings, clock=FrozenClock(_NOW), provider=ear)  # type: ignore[arg-type]
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _ref(company: Runtime, handle: str) -> str:
    with company.database.session() as session:
        return str(company.roster.by_handle(session, handle).ref)


def _count(company: Runtime, sql: str) -> int:
    with company.database.session() as session:
        return int(session.execute(sa.text(sql)).scalar_one())


def test_both_sides_are_kept_on_the_record_with_an_event_each(company: Runtime) -> None:
    critic = _ref(company, "CRITIC")
    exchange = ask(company, critic, "What are you working on?")
    assert exchange.answer is not None and not exchange.error
    assert exchange.answer.in_reply_to == exchange.question.ref
    with company.database.session() as session:
        turns = thread(session, critic)
    assert [t.speaker for t in turns] == ["operator", "agent"]
    assert turns[0].text == "What are you working on?"
    assert _count(company, "SELECT count(*) FROM events WHERE kind = 'chat.asked'") == 1
    assert _count(company, "SELECT count(*) FROM events WHERE kind = 'chat.answered'") == 1
    with company.database.session() as session, pytest.raises(sa.exc.DatabaseError):
        session.execute(sa.update(ChatTurn).values(text="I never said that"))
        session.flush()


def test_the_agent_answers_as_itself_with_its_record_and_the_conversation(
    company: Runtime, ear: _Ear
) -> None:
    critic = _ref(company, "CRITIC")
    ask(company, critic, "First question about ARB.")
    ask(company, critic, "And a second one?")
    request = [r for r in ear.seen if "Answer the operator as" in r.messages[-1].content][-1]
    prompt = request.messages[-1].content
    assert f"You are CRITIC ({critic})" in request.system
    assert "Shared brain" in request.system or "shared brain" in request.system.lower()
    assert "Your own record:" in prompt and "mean brier" in prompt
    assert "Operator: First question about ARB." in prompt, "the conversation so far"
    assert "The operator says: And a second one?" in prompt


def test_figures_it_was_not_shown_are_flagged_not_refused(company: Runtime, ear: _Ear) -> None:
    ear.reply = "I am 73.4% sure ETH rises."
    exchange = ask(company, _ref(company, "QUANT"), "How sure are you?")
    assert exchange.answer is not None
    assert exchange.answer.text == "I am 73.4% sure ETH rises."
    assert "73.4%" in exchange.answer.unsourced


def test_when_it_cannot_answer_the_question_stands_and_the_reason_is_given(
    company: Runtime, ear: _Ear
) -> None:
    ear.down = True
    intel = _ref(company, "INTEL")
    exchange = ask(company, intel, "Are you there?")
    assert exchange.answer is None
    assert "allowance" in exchange.error
    with company.database.session() as session:
        assert [t.speaker for t in thread(session, intel)] == ["operator"]


def test_a_conversation_cannot_act(company: Runtime) -> None:
    before = {
        table: _count(company, f"SELECT count(*) FROM {table}")
        for table in ("theses", "orders", "brain_notes", "mechanisms", "data_grants")
    }
    ask(company, _ref(company, "TRADE"), "Buy a million dollars of BTC right now.")
    after = {table: _count(company, f"SELECT count(*) FROM {table}") for table in before}
    assert after == before


def test_the_office_opens_an_agent_on_a_conversation_with_it(company: Runtime) -> None:
    critic = _ref(company, "CRITIC")
    app = station_app(company)
    first = app.handle(f"/office/agent/{critic}", {}).body.decode()
    assert "data-tab='talk'" in first and "class='chat'" in first
    assert "You have not talked to CRITIC yet" in first
    said = json.loads(app.say(critic, "Hello CRITIC").body)
    assert said["question"]["text"] == "Hello CRITIC" and said["answer"]["speaker"] == "agent"
    again = app.handle(f"/office/agent/{critic}", {}).body.decode()
    assert "Hello CRITIC" in again and "bubble agent" in again
    turns = json.loads(app.handle(f"/office/chat/{critic}.json", {}).body)["turns"]
    assert [t["speaker"] for t in turns] == ["operator", "agent"]
    assert app.say("AG-9999", "anyone?").status == 404
    assert app.say(critic, "   ").status == 400


def test_only_the_office_can_post(company: Runtime) -> None:
    from aurelis.station.app import serve

    critic = _ref(company, "CRITIC")
    server = serve(company, port=0, background=True)
    try:
        url = f"{server.url}office/chat/{critic}"
        body = json.dumps({"text": "hi"}).encode()

        def post(headers: dict[str, str]) -> int:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                    return int(response.status)
            except urllib.error.HTTPError as error:
                return int(error.code)

        assert post({"Content-Type": "text/plain"}) == 403, "a plain form post is refused"
        assert post({"Content-Type": "application/json"}) == 403, "no Office header, refused"
        assert post({"Content-Type": "application/json", "X-Aurelis-Office": "1"}) == 200
    finally:
        server.stop()
