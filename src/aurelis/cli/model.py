"""``aurelis model`` — which model answers, what it costs, and does it work.

Three commands, and the third is the only one in this repository that can spend
money or usage allowance. It is a separate command for exactly that reason:
everything else in the company runs offline against the mock provider, and the
one call that does not should be something a person types on purpose.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from aurelis.core.enums import ModelTier
from aurelis.core.errors import ProviderUnavailable
from aurelis.org.charters import CHARTERS
from aurelis.org.registry import resolve_authority
from aurelis.org.roster import LAUNCH_ROSTER
from aurelis.platform.llm.factory import KNOWN_PROVIDERS, raw_provider
from aurelis.platform.llm.pricing import PRICE_TABLE_VERSION, price_for
from aurelis.platform.llm.routing import routes_for
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

console = Console()

model_app = typer.Typer(
    help="Model routing: which tier reaches which model, and what it costs.",
    no_args_is_help=True,
)

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", "-w", help="Workspace root. Defaults to the current directory."),
]

_ORDER = (ModelTier.NONE, ModelTier.LOW, ModelTier.MID, ModelTier.HIGH)
"""The full ladder, NONE included.

Excluding it raised a ValueError the first time this ran, on GOV -- which holds
a NONE charter alongside eleven others. That is not a formatting problem: a
NONE charter held by a MID agent is work that should call no model at all,
routed to one. It is the sharpest version of the finding, so it is counted
separately rather than folded in."""


@model_app.command("routes")
def model_routes() -> None:
    """The routing table: provider, tier, model, price.

    ``ModelTier.NONE`` is deliberately absent from every row. It is a real tier
    covering seven charters, and it means the work is deterministic and no
    model is called — routing it anywhere would turn a function call that
    should exist into a bill nobody notices.
    """
    table = Table(title=f"model routing — prices at {PRICE_TABLE_VERSION}, USD per Mtok")
    for column in ("provider", "tier", "model", "input", "output"):
        table.add_column(column)
    for provider in KNOWN_PROVIDERS:
        for tier, model in routes_for(provider).items():
            price = price_for(model)
            table.add_row(
                provider,
                tier.value,
                model,
                str(price.input_per_mtok),
                str(price.output_per_mtok),
            )
    console.print(table)
    console.print(
        "\n[dim]A charter declares a tier; an agent's tier is the highest of "
        "the charters it covers, because it must be capable of its most "
        "demanding role. NONE is refused rather than routed.[/dim]"
    )


@model_app.command("tiers")
def model_tiers() -> None:
    """Which agents reach which model, and what generalists cost.

    The launch roster is seventeen agents covering seventy-six charters, so
    most of them hold charters at several tiers. An agent routes at its
    highest, which means a generalist holding one HIGH charter runs *all* its
    work on the most expensive model — including the LOW-tier charters it also
    holds.

    That is a measurable cost of generalists rather than an argument against
    them, and the company already has the machinery to act on it: fission (M11)
    moves a charter to its own agent, and after a split the low-tier work
    routes low.
    """
    by_tier = Counter(charter.tier.value for charter in CHARTERS.values())
    console.print(
        f"[bold]{len(CHARTERS)} charters[/bold]  "
        + "  ".join(f"{tier}={by_tier.get(tier, 0)}" for tier in ("none", "low", "mid", "high"))
    )
    console.print()

    table = Table(title="the launch roster, and the model each agent reaches")
    for column in (
        "agent",
        "charters",
        "tiers held",
        "routes at",
        "overpaying",
        "deterministic",
    ):
        table.add_column(column)

    overpaid = 0
    deterministic = 0
    for agent in LAUNCH_ROSTER:
        held = [CHARTERS[cid].tier for cid in agent.coverage]
        top = resolve_authority(agent.coverage).tier
        cheaper = sum(
            1
            for tier in held
            if tier is not ModelTier.NONE and _ORDER.index(tier) < _ORDER.index(top)
        )
        none_held = sum(1 for tier in held if tier is ModelTier.NONE)
        overpaid += cheaper
        deterministic += none_held
        table.add_row(
            agent.handle,
            str(len(agent.coverage)),
            ", ".join(sorted({tier.value for tier in held})),
            f"[bold]{top.value}[/bold]",
            f"{cheaper} charter(s)" if cheaper else "—",
            str(none_held) if none_held else "—",
        )
    console.print(table)
    console.print(
        f"\n[yellow]{overpaid} charter(s)[/yellow] are held by an agent that "
        "routes above the tier they were written for. Splitting one out through "
        "[bold]aurelis orgdev[/bold] moves it to an agent that routes at its own "
        "tier — which is a cost argument for fission the company can measure "
        "rather than assert."
    )
    if deterministic:
        console.print(
            f"[yellow]{deterministic} charter(s)[/yellow] are NONE tier — work "
            "that should call no model at all. The router refuses that tier, so "
            "reaching it is a bug rather than a bill; the column exists so the "
            "number is visible rather than assumed to be zero."
        )


@model_app.command("check")
def model_check(
    workspace: WorkspaceOption = None,
    tier: Annotated[str, typer.Option(help="Tier to route the test call at.")] = "low",
    yes: Annotated[
        bool, typer.Option("--yes", help="Make the call without confirming.")
    ] = False,
) -> None:
    """Make **one** real model call and report exactly what came back.

    This is the only command in the repository that reaches a provider. It
    routes at the cheapest tier by default, sends one short prompt, and prints
    the model, the text, the token counts, whether those counts were measured
    or estimated, the cost and the latency.

    The estimate question is the one worth running this for. The subscription
    path reports no marginal dollar cost and falls back to counting characters
    when the SDK does not report usage — so on that path, token budgets bind
    against an approximation. That is a real limitation and this is how you
    find out whether it applies to you.
    """
    from aurelis.core.config import load_settings

    settings = load_settings(home=workspace) if workspace else load_settings()
    provider = raw_provider(settings.provider)
    state = provider.availability()

    console.print(f"[bold]provider[/bold]  {settings.provider}")
    console.print(f"[bold]status[/bold]    {escape(state.detail)}")
    if not state.available:
        console.print(
            "\n[red]Not available.[/red] Nothing was called and nothing was "
            "spent. Install the extra it names, or point `provider` at another "
            "one in the workspace settings."
        )
        raise typer.Exit(code=1)

    chosen = ModelTier(tier)
    model = routes_for(settings.provider)[chosen]
    console.print(f"[bold]tier[/bold]      {chosen.value} -> {model}")

    if settings.provider != "mock" and not yes:
        console.print(
            "\n[yellow]This makes one real call.[/yellow] Re-run with --yes to "
            "proceed. Under a subscription it costs allowance rather than "
            "money; under the API it costs money."
        )
        raise typer.Exit(code=1)

    request = LlmRequest(
        model=ModelRef(provider=provider.name, model=model, tier=chosen, max_tokens=64),
        system="You are being checked for connectivity. Answer in one short sentence.",
        messages=(Message("user", "Reply with the single word: ready."),),
        actor="OPERATOR",
    )
    try:
        response = provider.complete(request)
    except ProviderUnavailable as error:
        console.print(f"\n[red]The call did not complete.[/red] {escape(str(error))}")
        raise typer.Exit(code=1) from None

    table = Table(show_header=False, box=None)
    table.add_column("", style="bold", width=18)
    table.add_column("")
    table.add_row("model", response.model.model)
    table.add_row("text", escape(response.text.strip()[:200]) or "[dim](empty)[/dim]")
    table.add_row("tokens in", str(response.usage.tokens_in))
    table.add_row("tokens out", str(response.usage.tokens_out))
    table.add_row(
        "counts are",
        "[yellow]ESTIMATED[/yellow] — budgets bind against an approximation"
        if response.usage.estimated
        else "[green]reported by the provider[/green]",
    )
    table.add_row("usd", str(response.usd))
    table.add_row("latency", f"{response.latency_ms} ms")
    table.add_row("stop reason", response.stop_reason)
    console.print()
    console.print(table)

    if response.usd == Decimal("0") and settings.provider == "agent_sdk":
        console.print(
            "\n[dim]Zero is a true statement about marginal cost on a "
            "subscription, not a missing value. The scarce resource there is "
            "allowance, which is why the budget ledger meters dollars and "
            "tokens separately.[/dim]"
        )
    if not response.text.strip():
        console.print(
            "\n[red]The provider returned no text.[/red] The call completed, so "
            "this is a wiring problem rather than an availability one."
        )
        raise typer.Exit(code=1)


@model_app.command("rehearse")
def model_rehearse(
    workspace: WorkspaceOption = None,
    seat: Annotated[str, typer.Option(help="Which seat: author or critic.")] = "author",
    samples: Annotated[int, typer.Option(help="How many answers to sample.")] = 5,
    tier: Annotated[str, typer.Option(help="Tier to route at.")] = "high",
    yes: Annotated[
        bool, typer.Option("--yes", help="Make the calls without confirming.")
    ] = False,
) -> None:
    """Ask a seat's question several times and classify every answer.

    A guard that silently rejects most of what a model says is worse than no
    guard: the seat looks occupied and produces nothing, and the only symptom
    is a command that fails. This turns that into a number.

    The first time a real model sat in the authoring seat it produced zero
    usable answers in five — three abstentions and two justifications citing
    figures it had derived rather than been shown. Both were fixed by saying
    what was meant, and this is how that was checked.
    """
    from aurelis.authoring.author import SYSTEM as AUTHOR_SYSTEM
    from aurelis.authoring.author import Citations, material_for
    from aurelis.authoring.design import question_for, slots_for
    from aurelis.authoring.standin import scripted_author
    from aurelis.core.config import load_settings
    from aurelis.meetings.types import ObjectionType
    from aurelis.platform.llm.rehearsal import rehearse
    from aurelis.platform.llm.seating import seat_provider
    from aurelis.training.critic import CRITIC_SYSTEM, critique_question
    from aurelis.training.standin import scripted_critic

    settings = load_settings(home=workspace) if workspace else load_settings()
    responder = scripted_author if seat == "author" else scripted_critic
    # Offline, rehearse the stand-in rather than the bare mock. A mock that
    # echoes its input scores zero for three, which is true and useless: it
    # measures the echo, not the seat. The stand-in is the baseline a real
    # model is compared against, and it is what CI should be reporting.
    provider = seat_provider(settings, responder) or raw_provider(settings.provider)
    state = provider.availability()
    console.print(f"[bold]provider[/bold]  {settings.provider}")
    if not state.available:
        console.print(f"[red]Not available.[/red] {escape(state.detail)}")
        raise typer.Exit(code=1)

    if seat == "author":
        question = question_for(slots_for(None)[0])
        material = material_for(
            "crypto", bars=2190, citations=Citations(task_ref="TSK-0001")
        )
        system = AUTHOR_SYSTEM
    elif seat == "critic":
        question = critique_question((ObjectionType.SURVIVORSHIP,))
        # The shape AgentCritic actually builds, key for key. A hand-made
        # approximation rehearsed the prompt rather than the seat: the section
        # names differed, the stand-in found no headline metric, and it
        # abstained three times out of three on evidence that plainly shows a
        # defect. A rehearsal of something the company never sends measures
        # nothing.
        material = {
            "the_specification": {
                "signal": "rotation",
                "lookback": 12,
                "universe_basis": "survivors_only",
                "bars": 400,
                "round_trip_cost_bps": "40",
            },
            "as_reported": {
                "sharpe": "0.42",
                "note": (
                    "this is one draw of history, which is all a researcher "
                    "ever has"
                ),
            },
            "mechanical_tests": {
                "survivorship": (
                    "varied run sharpe = 0.11; change against the original = "
                    "0.31; this is a corrective test (the varied run is the "
                    "truer one)"
                )
            },
        }
        system = CRITIC_SYSTEM
    else:
        console.print(f"[red]Unknown seat {seat!r}.[/red] Choose author or critic.")
        raise typer.Exit(code=1)

    if settings.provider != "mock" and not yes:
        console.print(
            f"\n[yellow]This makes {samples} real calls.[/yellow] Re-run with "
            "--yes to proceed."
        )
        raise typer.Exit(code=1)

    try:
        result = rehearse(
            provider,
            question=question,
            material=material,
            system=system,
            tier=ModelTier(tier),
            samples=samples,
        )
    except ProviderUnavailable as error:
        # The same treatment `model check` gives it. A rehearsal that runs out
        # of allowance halfway through has not found anything about the seat,
        # and saying so is more useful than a partial rate nobody can compare.
        console.print(f"\n[red]The rehearsal stopped.[/red] {escape(str(error))}")
        raise typer.Exit(code=1) from None

    table = Table(title=f"the {seat} seat, {result.model} at {result.tier.value}")
    for column in ("#", "outcome", "chose", "detail"):
        table.add_column(column, overflow="fold")
    for index, sample in enumerate(result.samples, 1):
        tone = "green" if sample.outcome == "usable" else "yellow"
        table.add_row(
            str(index),
            f"[{tone}]{sample.outcome}[/{tone}]",
            ", ".join(sample.chosen) or "—",
            escape(sample.detail[:120]),
        )
    console.print(table)

    console.print()
    console.print(f"[bold]{result.describe()}[/bold]")
    if result.choices:
        spread = ", ".join(f"{k}={v}" for k, v in sorted(result.choices.items()))
        console.print(f"what it picked: {spread}")
        if len(result.choices) == 1 and result.total > 1:
            console.print(
                "[dim]One answer every time. Conforming, but it has not decided "
                "anything the software could not have.[/dim]"
            )
    console.print(
        "\n[dim]Conformance measures whether an answer can be used, not whether "
        "it is right. Whether it is right is what the scenario suite and the "
        "selection correction are for.[/dim]"
    )
