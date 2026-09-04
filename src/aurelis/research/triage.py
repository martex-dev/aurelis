"""The Quantitative Research department's first work: questions and triage.

Two handlers that complete M2's three-agent chain.

.. code-block:: text

    INTEL   observes the desk           -> observation + briefing
      |     (task dependency)
    QUANT   reads the briefing,
            measures a second window    -> a research QUESTION
      |     (task dependency)
    LEAD-R  weighs the question         -> a DECISION to pursue or not

Nothing here creates a hypothesis, a finding or an experiment. Those are the
research lifecycle, they arrive at M4 with preregistration and the Registrar,
and building them now — before anything can lock a spec or refuse a run that
precedes its registration — would produce exactly the untraceable research the
whole design exists to prevent.

What this *does* demonstrate is agents genuinely working from each other's
output: QUANT reads a briefing it did not write, checks it against a second
measurement it obtained itself, and hands a question to a lead who decides.
Every claim cites the observation it came from.
"""

from __future__ import annotations

from aurelis.agents.interpret import interpret
from aurelis.agents.loop import AgentContext, TurnResult, register_handler
from aurelis.comms.tables import MessageKind, Priority
from aurelis.core.enums import ModelTier
from aurelis.org.scopes import ReadView, ToolScope

__all__ = ["QUESTION_TASK", "TRIAGE_TASK"]

QUESTION_TASK = "research.question"
TRIAGE_TASK = "research.triage"

_QUESTION_SYSTEM = """You are a quant researcher at Aurelis.

You are given an analyst's briefing and your own independent measurements of a \
second window. Write ONE research question worth investigating, in two or \
three sentences.

Hard rules:
- Use ONLY figures present in the material you were given.
- A question, not a conclusion. You have established nothing.
- Say what would have to be true for the question to be worth pursuing.
- If the two windows disagree, say so plainly; that is more interesting than \
if they agree."""

_TRIAGE_SYSTEM = """You are the lead researcher at Aurelis.

You are given a research question from your team. Decide whether it is worth a \
project, and say why in two or three sentences.

Hard rules:
- Use ONLY figures present in the material you were given.
- Deciding NOT to pursue is a good outcome and costs the company nothing. Most \
questions should be declined.
- Name the specific thing that would change your mind.
- Begin your answer with either PURSUE: or DECLINE:."""


@register_handler(QUESTION_TASK)
def raise_question(context: AgentContext) -> TurnResult:
    """Read the desk's briefing, check it independently, and ask a question."""
    desk = context.agent.desk.value if context.agent.desk else "crypto"

    observations = context.view(ReadView.DESK_OBSERVATIONS, limit=1)
    if not observations["observations"]:
        raise ValueError(
            f"no observation on the {desk} desk to work from; the briefing this "
            "task depends on produced nothing"
        )
    briefing = observations["observations"][0]

    # An independent second look, on a different window. The point is that the
    # researcher does not simply restate the analyst: it measures something
    # itself and can therefore disagree.
    second = context.use(
        ToolScope.DATA_OHLCV,
        desk=desk,
        symbol=context.task.payload.get("symbol"),
        limit=int(context.task.payload.get("bars", 96)),
    ).value
    measures = context.use(ToolScope.ENGINE_FEATURES, bars=second["bars"]).value

    material = {
        "briefing": {
            "ref": briefing["ref"],
            "author": briefing["author"],
            "statement": briefing["statement"],
            "as_of": briefing["as_of"],
            "source": briefing["source"],
        },
        "independent_measurements": measures,
        "window": f"{measures['bars']} bars",
    }

    interpretation = interpret(
        context, system=_QUESTION_SYSTEM, material=material, tier=ModelTier.MID
    )

    stored = context.artifacts.put_json(
        context.session,
        {"material": material, "question": interpretation.text},
        kind="research_question",
        produced_by=context.task.ref,
        actor=context.agent.ref,
    )

    lead = context.task.payload.get("ask")
    context.comms.post(
        context.session,
        from_agent=context.agent.ref,
        kind=MessageKind.QUESTION,
        channel_id=f"desk-{desk}",
        to_agents=(str(lead),) if lead else (),
        subject=f"Question from {measures['bars']} bars of {second['symbol']}",
        body=interpretation.text,
        claims=(f"independent window change: {measures['change']}",),
        evidence_refs=(briefing["ref"], stored.digest, second["data_digest"]),
        desk=desk,
        task_ref=context.task.ref,
        requires_response=bool(lead),
        at=context.clock.now(),
    )

    return TurnResult(
        summary=f"{context.agent.handle} asked a question about {second['symbol']}",
        artifact_digest=stored.digest,
        spend=interpretation.spend,
        produced={"question_artifact": stored.digest, "from_observation": briefing["ref"]},
    )


@register_handler(TRIAGE_TASK)
def triage_question(context: AgentContext) -> TurnResult:
    """Decide whether a question earns a project.

    Declining is the expected outcome and is recorded with the same prominence
    as pursuing. A lead that pursued everything would exhaust the company's
    budget on questions nobody weighed.
    """
    desk = context.agent.desk.value if context.agent.desk else "crypto"

    questions = [
        message
        for message in context.comms.read(
            context.session,
            channel_id=f"desk-{desk}",
            agent_ref=context.agent.ref,
            limit=20,
        )
        if message.kind == MessageKind.QUESTION.value
    ]
    if not questions:
        raise ValueError(
            f"no question on the {desk} desk to triage; the task this depends "
            "on produced nothing"
        )
    question = questions[-1]

    material = {
        "question": {
            "ref": question.ref,
            "from": question.from_agent,
            "body": question.body,
            "claims": list(question.claims),
            "cites": list(question.evidence_refs),
        }
    }

    interpretation = interpret(
        context, system=_TRIAGE_SYSTEM, material=material, tier=ModelTier.HIGH
    )

    verdict = "pursue" if interpretation.text.upper().startswith("PURSUE") else "decline"
    stored = context.artifacts.put_json(
        context.session,
        {"question_ref": question.ref, "verdict": verdict, "rationale": interpretation.text},
        kind="research_triage",
        produced_by=context.task.ref,
        actor=context.agent.ref,
    )

    context.comms.post(
        context.session,
        from_agent=context.agent.ref,
        kind=MessageKind.DECISION,
        channel_id=f"desk-{desk}",
        to_agents=(question.from_agent,),
        subject=f"Triage of {question.ref}: {verdict}",
        body=interpretation.text,
        claims=(f"verdict: {verdict}",),
        evidence_refs=(question.ref, stored.digest),
        desk=desk,
        task_ref=context.task.ref,
        priority=Priority.NORMAL,
        at=context.clock.now(),
    )

    return TurnResult(
        summary=f"{context.agent.handle} triaged {question.ref}: {verdict}",
        artifact_digest=stored.digest,
        spend=interpretation.spend,
        produced={"verdict": verdict, "question": question.ref},
    )

