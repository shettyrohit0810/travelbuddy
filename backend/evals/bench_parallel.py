"""Measure the real latency difference between sequential and parallel research.

Builds a sequential-edge variant of the production graph and runs both over the same
request, so the parallelism claim rests on a measured number rather than an edge
diagram. Reports cold and warm POI cache separately -- they differ by roughly two
orders of magnitude and only one of them describes steady state.

Usage (from backend/):
    python -m evals.bench_parallel
    python -m evals.bench_parallel --query "Plan a 3 day trip to Kyoto for 2 people with a budget of 40000"
"""
import argparse
import statistics
import sys
import time
from typing import Dict, List

from langgraph.graph import StateGraph, END

import app.agents.orchestrator as orch


def _build_sequential_graph():
    """The pre-parallel topology: research nodes chained one after another.

    Everything else -- nodes, routers, the verify/repair cycle -- is identical to
    production, so the only variable is whether the research phase overlaps.
    """
    wf = StateGraph(orch.OrchestratorState)
    wf.add_node("node_understanding", orch.understanding_node)
    wf.add_node("node_destination", orch.destination_node)
    wf.add_node("node_weather", orch.weather_node)
    wf.add_node("node_transport", orch.transport_node)
    wf.add_node("node_accommodation", orch.accommodation_node)
    wf.add_node("node_poi_prefetch", orch.poi_prefetch_node)
    wf.add_node("node_budget", orch.budget_node)
    wf.add_node("node_itinerary", orch.itinerary_node)
    wf.add_node("node_verify", orch.verification_node)
    wf.add_node("node_repair", orch.repair_node)
    wf.add_node("node_planner", orch.planner_node)

    wf.set_entry_point("node_understanding")
    wf.add_edge("node_understanding", "node_destination")
    # The difference: strictly serial research.
    wf.add_edge("node_destination", "node_weather")
    wf.add_edge("node_weather", "node_transport")
    wf.add_edge("node_transport", "node_accommodation")
    wf.add_edge("node_accommodation", "node_poi_prefetch")
    wf.add_edge("node_poi_prefetch", "node_budget")

    wf.add_edge("node_budget", "node_itinerary")
    wf.add_edge("node_itinerary", "node_verify")
    wf.add_conditional_edges(
        "node_verify", orch.verification_router,
        {"node_repair": "node_repair", "node_planner": "node_planner"},
    )
    wf.add_edge("node_repair", "node_itinerary")
    wf.add_edge("node_planner", END)
    return wf.compile()


def _initial_state(query: str) -> Dict:
    return {
        "query": query, "source_city": "Mumbai", "user_id": None,
        "requirements": None, "destination": None, "weather": None,
        "transport": [], "accommodation": [], "budget": None, "itinerary": None,
        "plan": None, "logs": [], "retries": 0, "replan_type": None,
        "poi_prefetch": None, "verification": None, "repair_attempts": 0,
        "repair_exhausted": False, "budget_baseline": None, "trajectories": [],
    }


def _time_graph(graph, query: str) -> float:
    started = time.perf_counter()
    graph.invoke(_initial_state(query))
    return time.perf_counter() - started


def _clear_poi_cache() -> None:
    from app.tools.poi_overpass import overpass_poi_search, _geocode
    from app.tools.destination_search import destination_search
    for fn in (overpass_poi_search, _geocode, destination_search):
        clear = getattr(fn, "cache_clear", None)
        if clear:
            clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="Plan a 3 day cultural trip to Kyoto for 2 people with a budget of 40000")
    parser.add_argument("--warm-repeats", type=int, default=5)
    parser.add_argument("--cold-repeats", type=int, default=5,
                        help="cold runs per configuration; each pays a real POI lookup")
    args = parser.parse_args()

    parallel = orch.orchestrator_graph
    sequential = _build_sequential_graph()

    print(f"query: {args.query}\n")
    rows: List[tuple] = []

    # --- cold: repeated, alternating order ------------------------------------
    # Each run clears the cache so it pays its own POI lookup. Order alternates so a
    # transient Overpass slowdown cannot systematically penalise one configuration --
    # a single-run comparison did exactly that once, inflating the reported speedup.
    seq_cold, par_cold = [], []
    for i in range(args.cold_repeats):
        first, second = (sequential, parallel) if i % 2 == 0 else (parallel, sequential)
        first_is_seq = i % 2 == 0
        _clear_poi_cache()
        t1 = _time_graph(first, args.query)
        _clear_poi_cache()
        t2 = _time_graph(second, args.query)
        (seq_cold if first_is_seq else par_cold).append(t1)
        (par_cold if first_is_seq else seq_cold).append(t2)
        print(f"  cold run {i+1}/{args.cold_repeats}: seq={seq_cold[-1]:.1f}s par={par_cold[-1]:.1f}s", flush=True)

    # --- warm: cache populated -------------------------------------------------
    seq_warm = [_time_graph(sequential, args.query) for _ in range(args.warm_repeats)]
    par_warm = [_time_graph(parallel, args.query) for _ in range(args.warm_repeats)]

    rows = [
        (f"cold POI cache (n={args.cold_repeats})", seq_cold, par_cold),
        (f"warm POI cache (n={args.warm_repeats})", seq_warm, par_warm),
    ]

    print()
    print(f"{'scenario':<28}{'seq median':<13}{'seq range':<20}{'par median':<13}{'par range':<20}{'speedup':<9}")
    print("-" * 103)
    for label, seq, par in rows:
        sm, pm = statistics.median(seq), statistics.median(par)
        speedup = f"{sm / pm:.2f}x" if pm > 0 else "n/a"
        print(
            f"{label:<28}{sm:<13.2f}{f'{min(seq):.1f}-{max(seq):.1f}':<20}"
            f"{pm:<13.2f}{f'{min(par):.1f}-{max(par):.1f}':<20}{speedup:<9}"
        )

    print(
        "\nMedians with full range, not single runs. Overpass latency varies widely "
        "(60-100s observed, plus occasional 504s), so quote the median and state the "
        "spread. Cold and warm describe different situations and neither alone is "
        "'the' latency."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
