"""Graph-level properties: concurrency, state merging, and honest degradation."""
import threading
import time
from unittest.mock import patch

from langgraph.graph import END, StateGraph

from app.agents.orchestrator import PlanState, plan_trip, research_join_node

BRANCH_DELAY_S = 0.4
BRANCHES = ["weather", "transport", "poi"]


def _probe_graph():
    """A miniature of the real fan-out, instrumented to observe concurrency.

    Parallelism is a claim about wall-clock behaviour, so it is measured rather than
    inferred from the edge list -- a diagram looks identical either way.
    """
    active, peak, lock = [], [0], threading.Lock()

    def make(name):
        def node(state):
            with lock:
                active.append(name)
                peak[0] = max(peak[0], len(active))
            time.sleep(BRANCH_DELAY_S)
            with lock:
                active.remove(name)
            return {"logs": [name]}
        return node

    graph = StateGraph(PlanState)
    graph.add_node("start", lambda s: {"logs": []})
    for name in BRANCHES:
        graph.add_node(name, make(name))
    graph.add_node("join", lambda s: {"logs": []})
    graph.set_entry_point("start")
    for name in BRANCHES:
        graph.add_edge("start", name)
        graph.add_edge(name, "join")
    graph.add_edge("join", END)
    return graph.compile(), peak


def _empty_state(**overrides) -> dict:
    base = {"query": "", "origin": "Mumbai", "logs": [], "trajectories": [],
            "transport": [], "repair_attempts": 0, "repair_exhausted": False}
    base.update(overrides)
    return base


def test_research_branches_run_concurrently():
    graph, peak = _probe_graph()
    started = time.perf_counter()
    graph.invoke(_empty_state())
    elapsed = time.perf_counter() - started

    assert peak[0] == len(BRANCHES), f"expected {len(BRANCHES)} concurrent, saw {peak[0]}"
    assert elapsed < BRANCH_DELAY_S * 2.5, f"{elapsed:.2f}s — looks sequential"


def test_concurrent_log_writes_are_merged_not_lost():
    """Without the operator.add reducer this raises InvalidUpdateError or silently
    keeps only one branch's entries."""
    graph, _ = _probe_graph()
    out = graph.invoke(_empty_state())
    assert sorted(x for x in out["logs"] if x) == sorted(BRANCHES)


def test_join_names_the_branches_that_came_back_empty():
    out = research_join_node(_empty_state(weather=None, transport=[], poi_lookup=None))
    joined = " ".join(out["logs"])
    for expected in ("weather", "transport", "attractions"):
        assert expected in joined
    assert "Proceeding" in joined


def test_join_is_quiet_when_everything_resolved():
    out = research_join_node(_empty_state(
        weather=object(), transport=[object()], poi_lookup={"activities": [{"name": "x"}]},
    ))
    assert "all branches returned data" in " ".join(out["logs"])


@patch("app.tools.geocoding.resolve_location", return_value=None)
def test_unresolvable_destination_degrades_without_crashing(mock_resolve):
    """An unknown place must produce an empty, honest plan -- never invented stops."""
    state = plan_trip("Plan a 2 day trip to Zzqxwblahfake123 with a budget of 20000")
    itinerary = state.get("itinerary")
    if itinerary is not None:
        assert all(len(day.stops) == 0 for day in itinerary.days)
    assert state.get("logs")
