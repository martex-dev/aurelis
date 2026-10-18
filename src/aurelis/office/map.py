"""The Office's floor plan: one room per department, and the Control Room (M61).

The art is Nullius's station, carried over: a side-on cutaway of a research
facility, rooms with furniture that belongs to their work, people at their
posts, hallways and lifts between them. What is new is what the rooms are.
Here a room is an Aurelis department, so the people in it are the agents the
record says are employed there, and the big room in the middle is the Control
Room, where the Company Manager sits and the whole company is reported at
once.

Plan units are a 200 by 124 grid, as in Nullius, scaled up when drawn. The
layout is three courses: the five research-to-trading departments across the
top, Executive, the Control Room and Knowledge in the middle, and the three
services along the bottom. Every room in the top and bottom courses sits over
a room in the middle one, so each has a lift down to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from aurelis.org.departments import Department

__all__ = ["CONTROL", "LINKS", "ROOMS", "OfficeRoom", "room_named", "room_of"]

CONTROL = "control"


@dataclass(frozen=True, slots=True)
class OfficeRoom:
    room_id: str
    name: str
    department: Department | None
    """None for the Control Room, which belongs to the whole company."""
    accent: str
    plain: str
    """What this room is for, said to somebody who has never read the code."""
    steps: tuple[str, ...]
    """What happens here, in order, in plain words."""
    x: float
    y: float
    w: float
    h: float


ROOMS: tuple[OfficeRoom, ...] = (
    OfficeRoom(
        "market_intelligence",
        "Market Intelligence",
        Department.MARKET_INTELLIGENCE,
        "cyan",
        "The company's eyes and ears. This room reads the world (prices, order books, news, "
        "X, Telegram, Discord, Reddit, new meme coins) and decides which sources are worth "
        "following.",
        (
            "Every hour the mailman brings fresh data: bars, books, funding, headlines, posts.",
            "The analysts here choose which sources and voices the company should follow.",
            "Voices are kept or dropped by whether their posts came before the move or after.",
            "They seal their own predictions too, and are graded like everyone else.",
        ),
        5,
        6,
        34,
        24,
    ),
    OfficeRoom(
        "quantitative_research",
        "Quant Research",
        Department.QUANTITATIVE_RESEARCH,
        "violet",
        "Where ideas become tests. The researchers here look for patterns in what the company "
        "has recorded and turn a hunch into a prediction that can be checked later.",
        (
            "The miner finds patterns in the recorded events (a spike, then another spike).",
            "A researcher looks at one and either explains why it should work or declines it.",
            "An explained pattern becomes a mechanism: it seals a prediction every time it fires.",
            "Predictions are graded against simply knowing the market's usual drift.",
        ),
        44,
        6,
        34,
        24,
    ),
    OfficeRoom(
        "strategy_laboratory",
        "Strategy Lab",
        Department.STRATEGY_LABORATORY,
        "orange",
        "The room that argues. Strategists propose, the Critic attacks every view before it is "
        "sealed, and the Validator checks that what looked good still holds.",
        (
            "A strategist states a view: which market, which way, how sure, by when.",
            "The Critic attacks it before it is sealed, and is itself graded on its attacks.",
            "Methods that keep losing to a coin toss are rewritten, by the best colleague.",
            "What survives is handed to Portfolio & Risk, never straight to trading.",
        ),
        83,
        6,
        34,
        24,
    ),
    OfficeRoom(
        "portfolio_and_risk",
        "Portfolio & Risk",
        Department.PORTFOLIO_AND_RISK,
        "crimson",
        "The room that can say no. Risk has its own authority: it sizes every paper position, "
        "caps how much any scheme may hold, and can stop trading altogether.",
        (
            "A scheme asks for a position. Risk decides the most it may have.",
            "The Portfolio Manager re-reads every scheme's record daily and moves capital.",
            "5% while a scheme is still proving itself, 10% when it earns, 0% when it loses.",
            "A kill latch here stops every order in the building.",
        ),
        122,
        6,
        34,
        24,
    ),
    OfficeRoom(
        "trading_operations",
        "Trading Floor",
        Department.TRADING_OPERATIONS,
        "green",
        "Where approved orders are carried out, on paper only. There is no live broker in this "
        "building. Fills, slippage and every round trip's result are recorded here.",
        (
            "An order arrives only after Risk has approved it.",
            "It fills at the newest price the wake can see, never at a better one.",
            "Every position is closed at its horizon and its result counted after fees.",
            "Nothing here can touch real money: the live adapter does not exist.",
        ),
        161,
        6,
        34,
        24,
    ),
    OfficeRoom(
        "executive",
        "Executive Suite",
        Department.EXECUTIVE,
        "gold",
        "The company's leadership: the research director and operations. They watch the "
        "health of the company and decide what it should work on next.",
        (
            "The research director writes a daily memo every agent reads.",
            "Operations watches the service: wakes, budgets, what broke.",
            "Leadership proposes changes to the company's own shape, and tests them.",
        ),
        5,
        41,
        34,
        40,
    ),
    OfficeRoom(
        CONTROL,
        "Control Room",
        None,
        "beacon",
        "The heart of the company. Everything every other room records arrives here, and the "
        "Company Manager watches over all of it. Start here: what is happening, who is doing "
        "it, what the company has learned, and how far it is from asking for real money.",
        (
            "Every room's activity is reported here as it happens.",
            "The Company Manager watches every agent, every room and every result.",
            "The company's own report card (the mandate) is checked every hour.",
            "When all fourteen conditions are met, this is where it asks you for real money.",
        ),
        44,
        41,
        112,
        40,
    ),
    OfficeRoom(
        "knowledge_and_memory",
        "Knowledge Vault",
        Department.KNOWLEDGE_AND_MEMORY,
        "magenta",
        "The company's memory. Every prediction, failure, note and decision is kept here "
        "forever, and the shared brain every agent reads before it answers is written here.",
        (
            "Every event goes onto a hash-chained record that cannot be rewritten.",
            "The shared brain (an Obsidian vault) is rendered from it every wake.",
            "Failed ideas are kept with the reason they failed, so nobody repeats them.",
        ),
        161,
        41,
        34,
        40,
    ),
    OfficeRoom(
        "audit_and_governance",
        "Audit Room",
        Department.AUDIT_AND_GOVERNANCE,
        "slate",
        "The independent checkers. Audit reads everyone else's work and looks for mistakes, "
        "shortcuts and anything that looks better than it should.",
        (
            "A daily audit reads the record for broken rules.",
            "An integrity check confirms the record has not been tampered with.",
            "Audit can challenge any department, including leadership.",
        ),
        5,
        92,
        60,
        24,
    ),
    OfficeRoom(
        "institutional_governance",
        "Governance Office",
        Department.INSTITUTIONAL_GOVERNANCE,
        "indigo",
        "The referee's office. Preregistration, scoring, custody of the evidence and the "
        "budget ledger live here: the rules that keep the company honest.",
        (
            "Every prediction is sealed here before its outcome exists.",
            "Every score is computed here, by software, not by an agent.",
            "Model calls and costs are counted against the budget.",
        ),
        70,
        92,
        60,
        24,
    ),
    OfficeRoom(
        "infrastructure",
        "Engine Room",
        Department.INFRASTRUCTURE,
        "teal",
        "The machinery: the service that wakes every hour, the data feeds, the browser that "
        "reads X and Discord, and the health checks that keep it all running.",
        (
            "The service wakes every hour and runs the company's day.",
            "Every vendor that fails is recorded, and the wake carries on.",
            "If the agents cannot think, the alarm goes off here first.",
        ),
        135,
        92,
        60,
        24,
    ),
)

LINKS: tuple[tuple[str, str], ...] = (
    # the top course, left to right
    ("market_intelligence", "quantitative_research"),
    ("quantitative_research", "strategy_laboratory"),
    ("strategy_laboratory", "portfolio_and_risk"),
    ("portfolio_and_risk", "trading_operations"),
    # the middle course
    ("executive", CONTROL),
    (CONTROL, "knowledge_and_memory"),
    # the bottom course
    ("audit_and_governance", "institutional_governance"),
    ("institutional_governance", "infrastructure"),
    # lifts: every top and bottom room down or up to the middle course
    ("market_intelligence", "executive"),
    ("quantitative_research", CONTROL),
    ("strategy_laboratory", CONTROL),
    ("portfolio_and_risk", CONTROL),
    ("trading_operations", "knowledge_and_memory"),
    ("executive", "audit_and_governance"),
    (CONTROL, "institutional_governance"),
    ("knowledge_and_memory", "infrastructure"),
)
"""Which rooms are joined by a hallway or a lift."""


def room_named(room_id: str) -> OfficeRoom:
    for room in ROOMS:
        if room.room_id == room_id:
            return room
    raise KeyError(room_id)


def room_of(department: str) -> str:
    """The room an agent of ``department`` works in."""
    for room in ROOMS:
        if room.department is not None and room.department.value == department:
            return room.room_id
    return CONTROL
