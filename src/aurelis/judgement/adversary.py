"""An adversary attacks a view before it is sealed, and is scored on the attack.

M25's first seven views on a real model all said *down*. Seven agents with
different charters read the same closes and reached the same conclusion in
different words: one opinion, written six times, scored as six. A thesis
nobody attacked has not been tested, and the brief is explicit that a critic
is scored on false discoveries caught, not on agreeableness.

So before a view is sealed, a different agent — one holding the critic or
adversarial charter — is shown the same material and the proposed view, and
asked for the strongest reason it is wrong, with a verdict: ``stands``,
``weakened`` or ``broken``. The author then sees the attack and answers:
``hold`` the view, ``revise`` its confidence, or ``withdraw`` it. All of it is
sealed with the view: the attack, the verdict, the confidence before and
after, and the response.

Both sides are then scored when the horizon expires. The author on its final
confidence, as before. The critic on whether its verdicts predicted failure:
a ``broken`` on a view that turned out wrong is a catch, a ``broken`` on a view
that turned out right is a false alarm, and a ``stands`` on a view that turned
out wrong is a miss. A critic that says ``broken`` to everything catches
everything and is useless, and the record will say so.

The attack is figure-checked like everything else. An attack that cannot be
read does not block the seal: the critic's failure is recorded against the
critic, and the view proceeds unattacked and says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from aurelis.agents.interpret import (
    FIGURE_RULE,
    allowed_figures,
    render_material,
    unsourced_numerals,
)
from aurelis.core.enums import ModelTier
from aurelis.platform.llm.routing import model_for
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

__all__ = [
    "ATTACK_FORM",
    "CRITIC_SYSTEM",
    "RESPONSE_FORM",
    "VERDICTS",
    "Adversary",
    "Attack",
    "Response",
    "parse_attack",
    "parse_response",
    "respond",
    "view_section",
]

VERDICTS: tuple[str, ...] = ("stands", "weakened", "broken")
RESPONSES: tuple[str, ...] = ("hold", "revise", "withdraw")

CRITIC_SYSTEM = (
    "You are the adversary at a research company that is building a forward "
    "track record. A colleague has proposed a view on a market. Your job is "
    "to find the strongest reason it is wrong, using only the material shown, "
    "and to say how badly it is hurt: `stands` if you found nothing that "
    "should change the view, `weakened` if the confidence is too high for the "
    "evidence, `broken` if the view should not be sealed at all.\n\n"
    "You are scored on whether your verdicts predict failure. A `broken` on a "
    "view that turns out wrong is a catch; a `broken` on a view that turns out "
    "right is a false alarm; a `stands` on a view that turns out wrong is a "
    "miss. Say `broken` to everything and you will catch everything and be "
    "useless. Attack the view, not the colleague."
)

ATTACK_FORM = (
    "Attack this view. Reply in exactly this form and nothing else:\n"
    "VERDICT: stands | weakened | broken\n"
    "ATTACK: <the strongest reason it is wrong, one to three sentences>\n\n"
    f"{FIGURE_RULE}"
)

RESPONSE_FORM = (
    "Respond to the attack on your view. Reply in exactly this form and nothing "
    "else:\n"
    "RESPONSE: hold | revise | withdraw\n"
    "CONFIDENCE: <your confidence now; the same number if you hold, a new one "
    "strictly above 0.5 and at most 1 if you revise, blank if you withdraw>\n"
    "BECAUSE: <one or two sentences>\n\n"
    "Withdrawing is legitimate and is recorded as such. Do not restate your "
    f"confidence inside BECAUSE. {FIGURE_RULE}"
)

_FIELD = re.compile(r"^\s*(VERDICT|ATTACK|RESPONSE|CONFIDENCE|BECAUSE)\s*:\s*(.*)$", re.I)


def _sections(text: str, prose: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).upper()
            out[current] = match.group(2).strip()
        elif current in prose and line.strip():
            out[current] = f"{out[current]} {line.strip()}".strip()
    return out


@dataclass(frozen=True, slots=True)
class Attack:
    """What the critic said, or that it could not be read."""

    critic_ref: str
    verdict: str
    text: str
    tokens: int
    usd: Decimal
    unreadable: bool = False

    @property
    def describe(self) -> str:
        return f"{self.critic_ref}: {self.verdict} — {self.text[:120]}"


@dataclass(frozen=True, slots=True)
class Response:
    """What the author did with the attack."""

    kind: str
    confidence: Decimal | None
    because: str
    tokens: int
    usd: Decimal


def view_section(view: Any, instrument: str) -> dict[str, str]:
    """The proposed view as material, so the attack and the response can cite it."""
    return {
        "instrument": instrument,
        "direction": view.direction,
        "horizon": view.horizon,
        "confidence": str(view.confidence),
        "thesis": view.thesis,
        "wrong_if": view.wrong_if,
    }


def parse_attack(text: str) -> tuple[str, str]:
    """Verdict and attack, or a ``ValueError`` saying which was unreadable."""
    fields = _sections(text, ("ATTACK",))
    verdict = fields.get("VERDICT", "").strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict {verdict or '<empty>'!r} is not one of {list(VERDICTS)}")
    attack = fields.get("ATTACK", "").strip()
    if len(attack) <= 20:
        raise ValueError("an attack of fewer than twenty characters is not one")
    return verdict, attack


def parse_response(text: str, *, stated: Decimal) -> tuple[str, Decimal | None, str]:
    """Response kind, the confidence now, and the reason — or a ``ValueError``."""
    fields = _sections(text, ("BECAUSE",))
    kind = fields.get("RESPONSE", "").strip().lower()
    if kind not in RESPONSES:
        raise ValueError(f"response {kind or '<empty>'!r} is not one of {list(RESPONSES)}")
    because = fields.get("BECAUSE", "").strip()
    if kind == "withdraw":
        return kind, None, because
    raw = fields.get("CONFIDENCE", "").strip().rstrip("%")
    if kind == "hold" and not raw:
        return kind, stated, because
    try:
        confidence = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"confidence {raw or '<empty>'!r} is not a number") from None
    if confidence > 1 and confidence <= 100:
        confidence = confidence / 100
    if not Decimal("0.5") < confidence <= 1:
        raise ValueError(f"confidence {confidence} is not strictly above 0.5 and at most 1")
    confidence = confidence.quantize(Decimal("0.01"))
    if kind == "hold" and confidence != stated:
        # A hold that moves the number is a revision wearing the wrong word.
        kind = "revise"
    if kind == "revise" and confidence == stated:
        kind = "hold"
    return kind, confidence, because


class Adversary:
    """One critic, asked to attack whatever view it is shown."""

    __slots__ = ("_provider", "critic_ref", "identity", "tier")

    def __init__(
        self, provider: Any, *, critic_ref: str, identity: str, tier: ModelTier = ModelTier.MID
    ) -> None:
        self._provider = provider
        self.critic_ref = critic_ref
        self.identity = identity
        self.tier = tier

    def attack(
        self,
        session: Session,
        *,
        material: dict[str, Any],
        view: Any,
        instrument: str,
        task_ref: str | None = None,
    ) -> Attack:
        shown = {**material, "the_view": view_section(view, instrument)}
        rendered = f"{render_material(shown)}\n\n{ATTACK_FORM}"
        model_id = model_for(self._provider.name, self.tier)
        response = self._provider.complete(
            session,
            LlmRequest(
                model=ModelRef(
                    provider=self._provider.name, model=model_id, tier=self.tier, max_tokens=400
                ),
                system=f"{CRITIC_SYSTEM}\n\n{self.identity}",
                messages=(Message("user", rendered),),
                actor=self.critic_ref,
                task_ref=task_ref,
            ),
        )
        try:
            verdict, text = parse_attack(response.text)
        except ValueError as error:
            return Attack(
                self.critic_ref, "unreadable", str(error), response.usage.total, response.usd, True
            )
        invented = unsourced_numerals(text, allowed_figures(shown, {"form": ATTACK_FORM}))
        if invented:
            return Attack(
                self.critic_ref,
                "unreadable",
                f"the attack cites {len(invented)} figure(s) the critic was not shown: "
                f"{', '.join(invented[:5])}",
                response.usage.total,
                response.usd,
                True,
            )
        return Attack(self.critic_ref, verdict, text, response.usage.total, response.usd)


def respond(
    provider: Any,
    session: Session,
    *,
    agent_ref: str,
    system: str,
    tier: ModelTier,
    material: dict[str, Any],
    view: Any,
    instrument: str,
    attack: Attack,
    task_ref: str | None = None,
) -> Response:
    """The author answers the attack. An unreadable answer is a hold, recorded as such."""
    shown = {
        **material,
        "the_view": view_section(view, instrument),
        "the_attack": {"by": attack.critic_ref, "verdict": attack.verdict, "attack": attack.text},
    }
    rendered = f"{render_material(shown)}\n\n{RESPONSE_FORM}"
    model_id = model_for(provider.name, tier)
    response = provider.complete(
        session,
        LlmRequest(
            model=ModelRef(provider=provider.name, model=model_id, tier=tier, max_tokens=300),
            system=system,
            messages=(Message("user", rendered),),
            actor=agent_ref,
            task_ref=task_ref,
        ),
    )
    try:
        kind, confidence, because = parse_response(response.text, stated=view.confidence)
    except ValueError as error:
        return Response(
            "hold",
            view.confidence,
            f"unreadable response, held: {error}",
            response.usage.total,
            response.usd,
        )
    invented = unsourced_numerals(because, allowed_figures(shown, {"form": RESPONSE_FORM}))
    if invented:
        return Response(
            "hold",
            view.confidence,
            f"response cited figures it was not shown ({', '.join(invented[:3])}); held",
            response.usage.total,
            response.usd,
        )
    return Response(kind, confidence, because, response.usage.total, response.usd)
