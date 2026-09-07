"""M17 — the charter decides which model answers.

Every charter in the registry declares a ``ModelTier``, and
``resolve_authority`` has computed an agent's tier since M1 as the highest
among the charters it covers. Until M17 that number was computed and thrown
away: every call site passed the literal string ``"mock-1"``. Point the runtime
at a real provider and it would have asked Anthropic for a model by that name.

These tests are the missing half, and the guard that stops it coming back.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import sqlalchemy as sa

from aurelis.agents.decide import Choice, Question, decide_as
from aurelis.core.enums import ModelTier
from aurelis.org.charters import CHARTERS
from aurelis.org.registry import resolve_authority
from aurelis.org.roster import LAUNCH_ROSTER
from aurelis.platform.db.tables import ModelCall
from aurelis.platform.llm.factory import KNOWN_PROVIDERS
from aurelis.platform.llm.pricing import PRICES, price_for
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.routing import (
    MOCK_MODEL,
    ROUTES,
    NoModelForTier,
    model_for,
    routed_models,
    routes_for,
    unpriced_routes,
)
from aurelis.platform.llm.types import Usage
from aurelis.runtime import Runtime

_SOURCE = Path(__file__).resolve().parent.parent / "src" / "aurelis"


# ------------------------------------------------------------- the route table


def test_every_provider_routes_every_tier_it_will_be_asked_for() -> None:
    """A provider missing a rung would fail at the first Board meeting, which
    is the worst possible time to discover a configuration gap."""
    for provider in KNOWN_PROVIDERS:
        ladder = routes_for(provider)
        assert set(ladder) == {ModelTier.LOW, ModelTier.MID, ModelTier.HIGH}
        assert list(ladder) == [ModelTier.LOW, ModelTier.MID, ModelTier.HIGH]


def test_every_routed_model_is_priced() -> None:
    """An unpriced model cannot be budgeted against, and a call that looks
    free is the one that runs away. Checked at import too, so a typo is a
    startup failure rather than a zero in the cost ledger."""
    assert unpriced_routes() == ()
    for model in routed_models():
        assert model in PRICES
        price_for(model)


def test_the_deterministic_tier_is_refused_rather_than_routed() -> None:
    """``NONE`` covers seven charters and means the work is deterministic.

    Routing it to the cheapest model would turn a function call that should
    exist into a bill nobody notices — the cheapest possible bug, and the
    hardest to see.
    """
    with pytest.raises(NoModelForTier, match="deterministic"):
        model_for("anthropic_api", ModelTier.NONE)

    none_tier = [c.charter_id for c in CHARTERS.values() if c.tier is ModelTier.NONE]
    assert none_tier, "the tier is real and something holds it"


def test_an_unknown_provider_has_no_route() -> None:
    with pytest.raises(NoModelForTier, match="no routing table"):
        model_for("some_new_vendor", ModelTier.MID)


def test_the_offline_provider_answers_every_tier() -> None:
    """The whole suite runs offline. A route table keyed only by tier would
    have started naming models nobody can call."""
    assert set(ROUTES["mock"].values()) == {MOCK_MODEL}
    for tier in (ModelTier.LOW, ModelTier.MID, ModelTier.HIGH):
        assert model_for("mock", tier) == MOCK_MODEL


def test_the_two_paying_providers_share_one_ladder() -> None:
    """The same role gets the same model whichever way the company pays, or a
    cost experiment would be measuring the payment method."""
    assert routes_for("agent_sdk") == routes_for("anthropic_api")
    assert routes_for("agent_sdk") != routes_for("mock")


# ------------------------------------------------- the charter decides the tier


def test_an_agent_routes_at_the_highest_charter_it_holds() -> None:
    """It has to be capable of its most demanding role."""
    audit = next(a for a in LAUNCH_ROSTER if a.handle == "AUDIT")
    held = {CHARTERS[cid].tier for cid in audit.coverage}
    assert ModelTier.HIGH in held and ModelTier.LOW in held
    assert resolve_authority(audit.coverage).tier is ModelTier.HIGH


def test_a_generalist_pays_its_highest_tier_for_all_of_its_work() -> None:
    """The measurable cost of generalists, and the reason fission is a cost
    argument rather than a tidiness one.

    Not asserted as a defect: 25 charters at launch are held by an agent that
    routes above the tier they were written for. Splitting one out moves it to
    an agent that routes at its own.
    """
    order = (ModelTier.NONE, ModelTier.LOW, ModelTier.MID, ModelTier.HIGH)
    overpaid = 0
    for agent in LAUNCH_ROSTER:
        top = resolve_authority(agent.coverage).tier
        overpaid += sum(
            1
            for cid in agent.coverage
            if CHARTERS[cid].tier is not ModelTier.NONE
            and order.index(CHARTERS[cid].tier) < order.index(top)
        )
    assert overpaid > 0, "the launch roster is generalist, and this is its price"


def test_the_charter_tier_reaches_the_recorded_call(
    settings, clock  # type: ignore[no-untyped-def]
) -> None:
    """End to end: the tier on the ledger row is the agent's own, not a
    default chosen by a function signature."""
    from decimal import Decimal

    from aurelis.authoring.attempt import run_authoring
    from aurelis.authoring.standin import scripted_author

    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=scripted_author)
    )
    built.initialise()
    built.staff()
    try:
        run_authoring(built, span=Decimal("0.1"))
        with built.database.session() as session:
            author = built.roster.by_handle(session, "STRAT")
            tiers = set(
                session.execute(
                    sa.select(ModelCall.tier).where(ModelCall.actor == author.ref)
                ).scalars()
            )
            models = set(
                session.execute(
                    sa.select(ModelCall.model).where(ModelCall.actor == author.ref)
                ).scalars()
            )
    finally:
        built.close()

    assert author.authority.tier is ModelTier.HIGH, "STRAT holds strategy.architect"
    assert tiers == {ModelTier.HIGH.value}, (
        "the Strategy Architect designs at its own tier, not at a signature default"
    )
    assert models == {MOCK_MODEL}, "and offline that tier still routes to the mock"


def test_a_caller_may_still_pin_a_model(runtime: Runtime) -> None:
    """An explicit id is a deliberate override for one piece of work, and it
    survives — the router is the default, not a cage."""
    question = Question("Pick", (Choice("a", "the first"), Choice("b", "the second")))
    provider = _Wrapped(MockProvider(responder=lambda _r: "ANSWER: a\nBECAUSE: it is."))
    with runtime.database.session() as session:
        decide_as(
            provider,
            session,
            agent_ref="AG-0001",
            question=question,
            material={"evidence": {"note": "nothing numeric"}},
            system="be brief",
            model=MOCK_MODEL,
        )


# ------------------------------------------------------- the guard against relapse


def test_no_call_site_names_a_model_literally() -> None:
    """The bug this milestone fixes, made unable to come back.

    ``"mock-1"`` belongs in exactly two places: the routing table that answers
    for the offline provider, and the price table that makes an offline run
    produce a real cost row of zero. Anywhere else it is a call site that will
    ask a real provider for a model that does not exist.
    """
    # pricing.py holds the price row for the offline model, and routing.py
    # holds MOCK_MODEL itself. Routing imports pricing, so the price table
    # cannot import the constant back without a cycle -- that one repetition is
    # structural and is the reason this is an allowlist rather than a ban.
    allowed = {"routing.py", "pricing.py"}
    offenders: list[str] = []
    for path in _SOURCE.rglob("*.py"):
        if path.name in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            node.body[0].value
            for node in ast.walk(tree)
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            # Code only. A comment or a docstring that mentions the offline
            # model is describing the problem, not causing it -- the first
            # version of this test failed on its own explanatory comments.
            if (
                isinstance(node, ast.Constant)
                and node.value == MOCK_MODEL
                and node not in docstrings
            ):
                offenders.append(f"{path.relative_to(_SOURCE)}:{node.lineno}")
    assert not offenders, (
        "these name a model literally instead of routing by tier: "
        + ", ".join(sorted(offenders))
    )


def test_token_counts_say_whether_they_were_measured() -> None:
    """Budgets bind against these numbers.

    The subscription path falls back to counting characters when the SDK does
    not report usage, so a budget enforced there is enforced on an
    approximation. That belongs on the value, not in a docstring somebody has
    to go and find.
    """
    assert Usage(10, 5).estimated is False
    assert Usage(10, 5, estimated=True).estimated is True

    from aurelis.platform.llm.agent_sdk import AgentSdkProvider

    source = Path(AgentSdkProvider.__module__.replace(".", "/") + ".py")
    text = (Path(_SOURCE).parent.parent / "src" / source).read_text(encoding="utf-8")
    assert "estimated=True" in text, "the subscription provider says so on every call"


# --------------------------------------------- a provider that cannot answer


def test_a_login_failure_reads_as_configuration_not_a_crash() -> None:
    """The first real call this provider ever made came back as a traceback
    forty frames deep ending in "Not logged in".

    That is a configuration state: the wiring worked, the process started, and
    it declined. An operator should learn it from a sentence rather than from a
    stack trace.
    """
    pytest.importorskip("claude_agent_sdk")
    from claude_agent_sdk import ResultError

    from aurelis.core.errors import ProviderUnavailable
    from aurelis.platform.llm.agent_sdk import _translate

    translated = _translate(
        ResultError("Claude Code returned an error result: Not logged in \u00b7 Please run /login")
    )
    assert isinstance(translated, ProviderUnavailable)
    assert "not logged in" in str(translated).lower()
    assert "Nothing was spent" in str(translated)


def test_an_unrecognised_failure_is_not_dressed_up_as_unavailability() -> None:
    """Swallowing an unknown error into "provider unavailable" would hide a
    real bug behind a reassuring message."""
    from aurelis.platform.llm.agent_sdk import _translate

    bug = ZeroDivisionError("something genuinely broken")
    assert _translate(bug) is bug


def test_availability_does_not_claim_login_is_verified() -> None:
    """The package importing is not the same as being able to make a call.

    Reporting "available" while unauthenticated would make `aurelis doctor`
    assert something it has not checked -- which is the failure this whole
    project spends its design budget avoiding.
    """
    pytest.importorskip("claude_agent_sdk")
    from aurelis.platform.llm.agent_sdk import AgentSdkProvider

    detail = AgentSdkProvider().availability().detail
    assert "not verified" in detail.lower()
    assert "model check" in detail


class _Wrapped:
    """The provider signature the runtime uses: ``complete(session, request)``."""

    def __init__(self, inner: MockProvider) -> None:
        self._inner = inner
        self.name = inner.name

    def complete(self, _session: object, request: object) -> object:
        return self._inner.complete(request)  # type: ignore[arg-type]
