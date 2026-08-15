"""The planning graph.

    understanding → [weather ∥ transport ∥ POI lookup] → budget
                                                           ↓
                        itinerary → verify → (repair → itinerary)* → assemble

Two properties are worth understanding before changing anything here.

**The research branches run concurrently.** They are independent given a destination, so
they fan out and join. Note that this buys less than it looks: one call (the POI lookup)
dominates total latency, so the measured gain is ~1.07x cold. The topology is right; the
payoff is small until the other branches do real network work.

**The verify/repair cycle is the only loop.** `verify` decides on arithmetic, `repair`
makes one targeted deterministic change, and the scheduler re-solves. It terminates on
success, an unrepairable violation, an attempt cap, or exhausted headroom -- bounded on
purpose, because an unbounded repair loop is a cost incident with extra steps.
"""
import logging
import operator
from typing import Annotated, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.budget import build_budget
from app.agents.itinerary import build_itinerary
from app.agents.transport import estimate_transport
from app.agents.understanding import parse_request
from app.schemas.trip import (
    BudgetBreakdown, Itinerary, TransportOption, TripRequirements, WeatherOutlook,
)
from app.scheduling.models import Coordinates
from app.verification.plan_verifier import (
    ACTIVITIES_OVERSPEND, BUDGET_OVERRUN, VerificationResult, verify_plan,
)

logger = logging.getLogger("app.agents.orchestrator")

MAX_REPAIR_ATTEMPTS = 2
MIN_CANDIDATES_PER_DAY = 3

# Order in which repair spends down allocations, most discretionary first. Transport is
# last and floored highest: it maps to a concrete priced option, so writing it down far
# is closer to lying about the price than to planning a cheaper trip.
REPAIR_LEVERS = ("activities", "food", "lodging", "transport")
REPAIR_FLOORS = {"activities": 0.0, "food": 0.4, "lodging": 0.5, "transport": 0.7}


class PlanState(TypedDict):
    query: str
    origin: str
    requirements: Optional[TripRequirements]
    destination: Optional[str]
    destination_coords: Optional[tuple]
    weather: Optional[WeatherOutlook]
    transport: List[TransportOption]
    poi_lookup: Optional[dict]
    budget: Optional[BudgetBreakdown]
    budget_baseline: Optional[BudgetBreakdown]
    itinerary: Optional[Itinerary]
    verification: Optional[VerificationResult]
    repair_attempts: int
    repair_exhausted: bool
    # Reducer-merged: parallel branches write these concurrently, and without an
    # explicit reducer LangGraph raises InvalidUpdateError on the second writer.
    logs: Annotated[List[str], operator.add]
    trajectories: Annotated[List[dict], operator.add]


def understanding_node(state: PlanState) -> dict:
    requirements = parse_request(state["query"])
    return {
        "requirements": requirements,
        "destination": requirements.destination,
        "logs": [f"Parsed request: destination={requirements.destination}, "
                 f"days={requirements.days}, budget={requirements.budget}"],
    }


def geocode_node(state: PlanState) -> dict:
    from app.tools.poi_overpass import resolve_location

    destination = state.get("destination")
    if not destination:
        return {"logs": ["No destination could be parsed from the request."]}

    resolution = resolve_location(destination)
    if resolution is None:
        return {"logs": [f"Could not resolve '{destination}' to a real place."]}

    return {
        "destination_coords": (resolution.lat, resolution.lon),
        "logs": [f"Resolved '{destination}' to {resolution.display_name}."],
    }


def weather_node(state: PlanState) -> dict:
    from app.tools.weather import weather_lookup

    destination = state.get("destination")
    if not destination:
        return {"logs": []}
    days = (state["requirements"].days if state.get("requirements") else None) or 3
    data = weather_lookup(destination, days)
    forecast = data.get("forecast") or []
    if not forecast:
        return {"logs": [f"No weather data available for {destination}."]}

    highs = [d["high_c"] for d in forecast if d.get("high_c") is not None]
    rains = [d["rain_chance_pct"] for d in forecast if d.get("rain_chance_pct") is not None]
    avg_rain = sum(rains) / len(rains) if rains else 0.0
    return {
        "weather": WeatherOutlook(
            summary=data.get("summary", ""),
            avg_high_c=round(sum(highs) / len(highs), 1) if highs else None,
            rain_chance_pct=round(avg_rain, 1),
            suitability=max(0, min(100, int(100 - avg_rain))),
            warnings=["High chance of rain across the trip."] if avg_rain > 60 else [],
            source=data.get("source", "open-meteo"),
        ),
        "logs": [f"Weather resolved for {destination}."],
    }


def transport_node(state: PlanState) -> dict:
    from app.tools.poi_overpass import resolve_location

    coords = state.get("destination_coords")
    if not coords:
        return {"logs": []}
    origin = resolve_location(state.get("origin") or "Mumbai")
    if origin is None:
        return {"logs": ["Could not resolve the origin city; skipping transport."]}

    travelers = (state["requirements"].travelers if state.get("requirements") else None) or 1
    options = estimate_transport(
        Coordinates(origin.lat, origin.lon), Coordinates(*coords), travelers
    )
    return {"transport": options, "logs": [f"Estimated {len(options)} transport option(s)."]}


def poi_node(state: PlanState) -> dict:
    """Fetch attractions, escalating to the acquisition agent when the pool is thin."""
    from app.tools.destination_search import destination_search

    destination = state.get("destination")
    if not destination:
        return {"logs": []}

    days = (state["requirements"].days if state.get("requirements") else None) or 3
    needed = days * MIN_CANDIDATES_PER_DAY
    lookup = destination_search(destination)
    found = lookup.get("results_count", 0)
    logs = [f"POI lookup: {found} candidate(s) for {destination}."]

    if found >= needed:
        return {"poi_lookup": lookup, "logs": logs}

    logs.append(f"Below the {needed} a {days}-day trip needs; escalating to the "
                f"acquisition agent.")
    improved, trajectory = _run_acquisition_agent(destination, found, needed)
    logs.append(f"Acquisition agent: {trajectory.outcome} — {trajectory.summary}")
    return {
        "poi_lookup": improved or lookup,
        "logs": logs,
        "trajectories": [trajectory.to_dict()],
    }


def _run_acquisition_agent(destination: str, found: int, needed: int):
    """Bounded agent that may widen retrieval only. It never touches the scheduler,
    the verifier, or budget arithmetic -- it decides what to look up, nothing else."""
    from app.agents import acquisition_tools
    from app.agents.agent_loop import LLMBrain, NoBrainAvailable, run_agent
    from app.agents.trajectory import Trajectory

    goal = (f"Find at least {needed} real points of interest for a trip to "
            f"{destination!r}. The default lookup found only {found}.")

    try:
        brain = LLMBrain()
    except NoBrainAvailable as exc:
        trajectory = Trajectory(agent="acquisition", goal=goal)
        trajectory.outcome = "unavailable"
        trajectory.summary = (f"No LLM configured ({exc}); no agent ran. Proceeding with "
                              f"the {found} candidate(s) already found.")
        trajectory.record("outcome", "unavailable", reasoning=trajectory.summary)
        return None, trajectory

    def summarise(_tool_name, observation):
        if isinstance(observation, dict) and "pois" in observation:
            return {k: v for k, v in observation.items() if k != "pois"}
        return observation

    trajectory = run_agent(
        agent_name="acquisition", goal=goal, brain=brain,
        tool_specs=acquisition_tools.TOOL_SPECS,
        tool_impls=acquisition_tools.TOOL_IMPLS,
        max_tool_calls=6, wall_clock_budget_s=120.0,
        observation_summarizer=summarise,
    )

    # Read results out of recorded observations, never from the agent's own summary, so
    # it cannot report finding places it did not actually retrieve.
    best = None
    for step in trajectory.steps:
        observation = step.observation
        if step.name == "search_pois" and isinstance(observation, dict) and observation.get("pois"):
            if best is None or len(observation["pois"]) > len(best["pois"]):
                best = observation
    if not best:
        return None, trajectory

    return {
        "destination": destination, "resolved_location": None,
        "results_count": len(best["pois"]), "activities": best["pois"],
        "source": "overpass",
    }, trajectory


def research_join_node(state: PlanState) -> dict:
    missing = []
    if not state.get("weather"):
        missing.append("weather")
    if not state.get("transport"):
        missing.append("transport")
    lookup = state.get("poi_lookup")
    if not lookup or not lookup.get("activities"):
        missing.append("attractions")
    if missing:
        return {"logs": [f"Research complete with gaps: {', '.join(missing)}. "
                         f"Proceeding with what resolved."]}
    return {"logs": ["Research complete; all branches returned data."]}


def budget_node(state: PlanState) -> dict:
    requirements = state.get("requirements")
    days = (requirements.days if requirements else None) or 3
    travelers = (requirements.travelers if requirements else None) or 1
    budget = build_budget(
        requirements.budget if requirements else None,
        state.get("transport") or [], days, travelers,
    )
    return {"budget": budget, "logs": [f"Budget allocated; total {budget.total}."]}


def itinerary_node(state: PlanState) -> dict:
    requirements = state.get("requirements")
    destination = state.get("destination") or "Unknown"
    days = (requirements.days if requirements else None) or 3
    budget = state.get("budget")

    itinerary = build_itinerary(
        destination=destination, days=days,
        activities_budget=budget.activities if budget else None,
        start_coords=None,
        prefetched=state.get("poi_lookup"),
    )
    scheduled = sum(len(d.stops) for d in itinerary.days)
    return {"itinerary": itinerary, "logs": [f"Itinerary built with {scheduled} stop(s)."]}


def verification_node(state: PlanState) -> dict:
    result = verify_plan(state.get("requirements"), state.get("budget"), state.get("itinerary"))
    if result.valid:
        return {"verification": result, "logs": ["Verification: plan satisfies all hard constraints."]}
    return {
        "verification": result,
        "logs": [f"Verification VIOLATION [{v.code}] {v.message}" for v in result.violations],
    }


def _headroom(budget: BudgetBreakdown, baseline: Optional[BudgetBreakdown]) -> float:
    baseline = baseline or budget
    return sum(
        max(round(getattr(budget, lever) - getattr(baseline, lever) * REPAIR_FLOORS[lever], 2), 0.0)
        for lever in REPAIR_LEVERS
    )


def repair_node(state: PlanState) -> dict:
    """Spend the overspend down across levers in order, each bounded by a floor.

    Floors are anchored to a baseline captured on the first pass. Deriving them from the
    *current* value instead lets each pass shave another fraction, so a lever approaches
    zero without ever reaching a floor and 'exhausted' never fires.
    """
    budget = state["budget"]
    baseline = state.get("budget_baseline") or budget
    attempts = state.get("repair_attempts", 0) + 1
    verification = state.get("verification")

    overspends = [
        v.overspend for v in (verification.violations if verification else [])
        if v.code in (BUDGET_OVERRUN, ACTIVITIES_OVERSPEND) and v.overspend
    ]
    remaining = max(overspends) if overspends else 0.0

    values = {lever: getattr(budget, lever) for lever in REPAIR_LEVERS}
    pulled = []
    for lever in REPAIR_LEVERS:
        if remaining <= 0:
            break
        floor = round(getattr(baseline, lever) * REPAIR_FLOORS[lever], 2)
        available = max(round(values[lever] - floor, 2), 0.0)
        if available <= 0:
            continue
        take = min(available, remaining)
        values[lever] = round(values[lever] - take, 2)
        remaining = round(remaining - take, 2)
        pulled.append(f"{lever} → {values[lever]}")

    repaired = BudgetBreakdown(**values, buffer=budget.buffer)
    repaired.total = round(sum(values.values()) + budget.buffer, 2)

    exhausted = not pulled
    if exhausted:
        message = (f"Repair {attempts}/{MAX_REPAIR_ATTEMPTS}: every lever is at its floor; "
                   f"cannot absorb the remaining overspend. Reporting it honestly.")
    else:
        shortfall = f" Still {remaining} short." if remaining > 0 else ""
        message = (f"Repair {attempts}/{MAX_REPAIR_ATTEMPTS}: {', '.join(pulled)}; "
                   f"re-solving against the tighter ceiling.{shortfall}")

    return {
        "budget": repaired, "budget_baseline": baseline,
        "repair_attempts": attempts, "repair_exhausted": exhausted,
        "logs": [message],
    }


def verification_router(state: PlanState) -> str:
    verification = state.get("verification")
    if verification is None or verification.valid:
        return "assemble"
    if not verification.repairable:
        return "assemble"
    if state.get("repair_exhausted"):
        return "assemble"
    if state.get("repair_attempts", 0) >= MAX_REPAIR_ATTEMPTS:
        return "assemble"
    budget = state.get("budget")
    # Check headroom before dispatching: with none left, a repair pass would re-run the
    # whole scheduler to reach an identical plan.
    if budget is not None and _headroom(budget, state.get("budget_baseline")) <= 0:
        return "assemble"
    return "repair"


def assemble_node(state: PlanState) -> dict:
    return {"logs": ["Plan assembled."]}


def _build_graph():
    graph = StateGraph(PlanState)
    graph.add_node("understanding", understanding_node)
    graph.add_node("geocode", geocode_node)
    graph.add_node("weather", weather_node)
    graph.add_node("transport", transport_node)
    graph.add_node("poi", poi_node)
    graph.add_node("research_join", research_join_node)
    graph.add_node("budget", budget_node)
    graph.add_node("itinerary", itinerary_node)
    graph.add_node("verify", verification_node)
    graph.add_node("repair", repair_node)
    graph.add_node("assemble", assemble_node)

    graph.set_entry_point("understanding")
    graph.add_edge("understanding", "geocode")

    # Fan out: independent given a resolved destination.
    for branch in ("weather", "transport", "poi"):
        graph.add_edge("geocode", branch)
        graph.add_edge(branch, "research_join")

    graph.add_edge("research_join", "budget")
    graph.add_edge("budget", "itinerary")
    graph.add_edge("itinerary", "verify")
    graph.add_conditional_edges("verify", verification_router,
                                {"repair": "repair", "assemble": "assemble"})
    graph.add_edge("repair", "itinerary")
    graph.add_edge("assemble", END)
    return graph.compile()


plan_graph = _build_graph()


def plan_trip(query: str, origin: str = "Mumbai") -> PlanState:
    initial: PlanState = {
        "query": query, "origin": origin, "requirements": None, "destination": None,
        "destination_coords": None, "weather": None, "transport": [], "poi_lookup": None,
        "budget": None, "budget_baseline": None, "itinerary": None, "verification": None,
        "repair_attempts": 0, "repair_exhausted": False, "logs": [], "trajectories": [],
    }
    return plan_graph.invoke(initial)
