"""Who sits behind a seat: a real model when one is configured, else a stand-in.

M14, M15 and M16 each built a seat an agent sits in, and each wired the seat
directly to a deterministic stand-in. That was right while there was nothing
else: every model call in this repository ran against the mock provider, and a
mock that echoes its input cannot answer a multiple-choice question, so without
a scripted responder the seats would have been unrunnable.

M17 gave the company a real provider. Leaving the wiring as it was would have
made the stand-in permanent — three commands that *say* they seat an agent and
always seat a script, whatever the workspace is configured to use.

So the rule is one line and it lives in one place: **the stand-in answers only
for the offline provider.** Configure anything else and the seat gets what the
workspace was pointed at, through the same routing every other call uses.

Keeping the fallback rather than deleting it is deliberate. The whole test
suite, the CI acceptance run and every offline demonstration depend on the
seats being answerable with no credentials and no cost, and a seat that only
works when somebody is signed in would take the company's own demonstrations
away from anyone who has not signed in yet.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aurelis.platform.llm.providers import MockProvider, ModelProvider
from aurelis.platform.llm.types import LlmRequest

__all__ = ["seat_provider", "standins", "stands_in"]


def stands_in(provider_name: str) -> bool:
    """Whether this provider needs a script to answer a closed question."""
    return provider_name == "mock"


def seat_provider(
    settings: Any, responder: Callable[[LlmRequest], str]
) -> ModelProvider | None:
    """The provider to seat, or ``None`` to use whatever is configured.

    Returning ``None`` rather than building the configured provider keeps this
    module out of the credential path: :func:`~aurelis.runtime.Runtime.build`
    already knows how to construct a provider from settings, and a second
    place that did the same thing would be a second place to get it wrong.
    """
    if stands_in(settings.provider):
        return MockProvider(responder=responder)
    return None


def standins() -> Callable[[LlmRequest], str]:
    """Every scripted seat behind one responder, for commands that seat several.

    The autonomy loop puts agents in the author's seat and the judgement seat
    in the same run. Each stand-in recognises its own prompt and answers only
    that; the judge is asked first because its prompts are the more specific.
    """
    from aurelis.authoring.standin import scripted_author
    from aurelis.judgement.standin import scripted_judge

    def respond(request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        if "Which market do you want" in prompt or "State your view on" in prompt:
            return scripted_judge(request)
        return scripted_author(request)

    return respond
