"""A Brainstorm that starts by reading the file.

The Brainstorm protocol already asks "What has been tried before, and what
happened?" — and until now the room had no way to answer it. Agents would
answer from whatever the model happened to associate with the words, which is
the exact failure this company exists to avoid: confident recall of research
nobody did.

So the ceremony assembles the evidence pack from the record before anyone
speaks. Prior art goes into the pack, which the Chair stores as an artifact, so
the room's answer to "have we tried this?" is a citable object rather than a
recollection. Standing rules go in beside it, because a room brainstorming
inside constraints it does not know about will spend its rounds proposing work
that is already forbidden.

This lives in ``memory`` rather than ``meetings`` for a boring reason and a
good one. The boring one: ``memory`` already depends on ``meetings``, and the
reverse edge would be a cycle. The good one: this *is* a memory ceremony. What
makes it different from any other Brainstorm is entirely what the corpus hands
the room at the start.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.meetings.chair import Chair, MeetingOutcome
from aurelis.meetings.types import MeetingType
from aurelis.memory.lessons import Lessons, StandingRules
from aurelis.memory.priorart import PriorArtReport, search
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["BrainstormOutcome", "evidence_pack", "hold_brainstorm"]


@dataclass(frozen=True, slots=True)
class BrainstormOutcome:
    """The meeting, and what the corpus told it before it started."""

    meeting: MeetingOutcome
    prior_art: PriorArtReport
    rules: StandingRules

    def describe(self) -> str:
        return "\n".join(
            [
                f"{self.meeting.ref}: {self.meeting.describe()}",
                f"  {self.prior_art.describe()}",
                f"  {self.rules.describe()}",
            ]
        )


def evidence_pack(
    session: Session,
    *,
    question: str,
    family: str,
    desk: str | None = None,
    lessons: Lessons | None = None,
    limit: int = 5,
    ledger: Ledger | None = None,
    at: dt.datetime | None = None,
) -> tuple[dict[str, object], PriorArtReport, StandingRules]:
    """Everything the record can tell a room before it starts guessing.

    Returned as a plain dict for the Chair alongside the typed reports, because
    the pack is stored as an artifact and has to survive JSON, while the caller
    usually wants to assert on the objects.
    """
    report = search(session, claim=question, family=family, limit=limit)
    rules = (lessons or Lessons()).binding(session, family=family, desk=desk)

    if ledger is not None:
        ledger.append(
            session,
            kind=EventKind.PRIOR_ART_SEARCHED,
            actor=Actor.SYSTEM,
            subject=family,
            payload={
                "question": question[:400],
                "searched": report.searched,
                "matches": list(report.refs),
                "corpora": list(report.corpora),
                "novel_to_this_index": report.novel,
            },
            at=at,
        )

    pack: dict[str, object] = {
        "question": question,
        "family": family,
        "we_tried_this_before": report.as_payload(),
        "standing_rules": rules.as_payload(),
    }
    if not report.searched:
        pack["prior_art_caveat"] = (
            "nothing is indexed, so the absence of prior art means the corpus "
            "is empty rather than the idea being new"
        )
    elif report.novel:
        pack["prior_art_caveat"] = (
            f"no close match among {report.searched} indexed trials; this is a "
            "statement about what has been indexed, not about the literature"
        )
    return pack, report, rules


def hold_brainstorm(
    session: Session,
    *,
    chair: Chair,
    question: str,
    family: str,
    chair_ref: str,
    participants: tuple[str, ...],
    desk: str | None = None,
    lessons: Lessons | None = None,
    ledger: Ledger | None = None,
    clock: Clock | None = None,
    at: dt.datetime | None = None,
) -> BrainstormOutcome:
    """Convene a Brainstorm whose evidence pack is the corpus.

    The room diverges — that is what a Brainstorm is for — but it diverges from
    what the company actually knows, and every participant sees the same prior
    art. An idea that was killed three years ago can still be proposed here;
    what it cannot do is be proposed *as if it were new*.
    """
    moment = at or (clock or SystemClock()).now()
    pack, report, rules = evidence_pack(
        session,
        question=question,
        family=family,
        desk=desk,
        lessons=lessons,
        ledger=ledger,
        at=moment,
    )

    meeting = chair.convene(
        session,
        meeting_type=MeetingType.BRAINSTORM,
        subject=f"Brainstorm: {question[:180]}",
        chair=chair_ref,
        participants=participants,
        desk=desk,
        trigger="the corpus was searched for prior art before the room opened",
        evidence=pack,
        at=moment,
    )
    outcome = chair.run(session, meeting.ref, at=moment)
    return BrainstormOutcome(meeting=outcome, prior_art=report, rules=rules)
