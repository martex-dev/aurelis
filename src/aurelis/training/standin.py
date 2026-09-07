"""A scripted reasoner, so the seat can be exercised without a model.

Every model call in this repository runs against the mock provider by default:
no credentials, no network, no cost. That is a deliberate property of the
architecture and it does not change here — but a mock that echoes its input
cannot answer a multiple-choice question, so the critic's seat would be
untestable without something to sit in it.

This is that something, and it is **not an agent**. It is a deterministic
function of the prompt that reads the degradation figures out of the rendered
material and applies a rule. What it exercises is the machinery around the
seat: the closed option set, the parse, the figure check, the refusal path, and
the scoring against measured truth. Point the runtime at a real provider and
the same code path asks a real model instead; nothing else changes.

It is deliberately given a **different policy** from the shipped playbook —
readier to allege, on a lower bar — so that comparing the two produces a real
trade-off rather than an identity. A stand-in tuned to agree with the incumbent
would make the comparison say nothing.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from aurelis.agents.decide import NOTHING
from aurelis.platform.llm.types import LlmRequest

__all__ = ["EAGER_BAR", "scripted_critic"]

EAGER_BAR = Decimal("0.005")
"""The stand-in's bar for alleging a defect, in metric units.

Half the shipped playbook's smallest threshold. Chosen to be *different*, not
to be better: the point of running it against the incumbent is to see what a
readier critic costs in false alarms, and a stand-in that matched the
thresholds would produce an identity and teach nothing.
"""

_TEST = re.compile(
    r"^\s*([a-z_]+):\s*varied run .*?change against the original = "
    r"(-?\d+(?:\.\d+)?).*?this is a (corrective|stress) test",
    re.MULTILINE,
)
_REPORTED = re.compile(r"As Reported:(?P<block>(?:\n\s+\S.*)+)", re.IGNORECASE)
"""The whole As Reported block, not just the line after the heading.

``render_material`` sorts a section's keys, so the caveat line sorts above the
measurement and the first line under the heading is prose. Anchored to that
line this matched nothing, ``had_a_result`` was false on every scenario, and
**every stress defect was suppressed everywhere** -- the stand-in scored four
catches out of eight and read like a considered difference of judgement rather
than a broken regex.
"""

_FIGURE = re.compile(r":\s*(-?\d+(?:\.\d+)?)\s*$", re.MULTILINE)


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except InvalidOperation:  # pragma: no cover - the regex guarantees digits
        return None


def scripted_critic(request: LlmRequest) -> str:
    """Answer a critique question from the figures in the prompt.

    Applies the same two-kind rule the taxonomy declares (ADR-0011): a
    corrective test is settled by degradation, a stress test only bites when
    there was a result for it to remove. Everything it cites is a number that
    appeared in the material, because the figure check would otherwise reject
    the answer -- which is the guard doing its job on the stand-in exactly as
    it would on a model.
    """
    prompt = request.messages[-1].content
    reported = _REPORTED.search(prompt)
    headline = None
    if reported is not None:
        figures = _FIGURE.findall(reported.group("block"))
        headline = _decimal(figures[0]) if figures else None
    had_a_result = headline is not None and headline > Decimal("0.01")

    alleged: list[str] = []
    cited: list[str] = []
    for match in _TEST.finditer(prompt):
        defect, raw, kind = match.group(1), match.group(2), match.group(3)
        degradation = _decimal(raw)
        if degradation is None or degradation < EAGER_BAR:
            continue
        if kind == "stress" and not had_a_result:
            # A stress objection against a specification that never showed a
            # result settles nothing. Alleging it anyway is how a critic gets
            # a perfect catch rate and a useless one.
            continue
        alleged.append(defect)
        cited.append(raw)

    if not alleged:
        return (
            f"ANSWER: {NOTHING}\n"
            "BECAUSE: no varied run moved the headline metric far enough to "
            "support an allegation."
        )
    return (
        f"ANSWER: {', '.join(alleged)}\n"
        f"BECAUSE: the varied runs moved the headline metric by {', '.join(cited)}, "
        "which is past the bar for raising these."
    )
