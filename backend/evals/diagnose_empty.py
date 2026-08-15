"""Diagnose WHY a benchmark case schedules zero stops.

Written because "five of ten cases schedule zero stops" is not actionable -- the causes
are different per case and the fixes are different too. This walks the same path the
planner takes and reports where the candidates actually disappear:

  geocode -> POI provider -> coordinate/name filter -> budget knapsack -> schedule

Reports the first stage that produced nothing, rather than inferring from the empty
result at the end. Usage (from backend/):

    python -m evals.diagnose_empty
    python -m evals.diagnose_empty --case goa_generous_budget
"""
import argparse
import sys
from typing import Any, Dict, List

from evals.cases import CASES


def _diagnose(case) -> Dict[str, Any]:
    from app.agents.understanding import parse_trip_request
    from app.tools.poi_overpass import _geocode
    from app.tools.destination_search import destination_search
    from app.agents.itinerary import _fetch_candidates
    from app.schemas.itinerary import ItineraryRequest
    from app.agents.itinerary import generate_itinerary

    report: Dict[str, Any] = {"case": case.name, "query": case.query}

    # Stage 1 -- what destination did we even parse?
    reqs = parse_trip_request(case.query)
    destination = reqs.destination if reqs.destination and reqs.destination != "Unknown" else None
    report["parsed_destination"] = reqs.destination
    report["days"] = reqs.days
    report["stated_budget"] = reqs.budget
    if not destination:
        # The orchestrator substitutes a recommendation here; record that explicitly
        # because a substituted destination is a different failure from a missing one.
        report["stage_failed"] = "understanding: no destination parsed"
        report["note"] = "orchestrator would substitute a recommended destination"
        return report

    # Stage 2 -- geocoding
    geo = _geocode(destination)
    report["geocoded"] = geo[2] if geo else None
    if geo is None:
        report["stage_failed"] = "geocode: no match"
        return report
    if destination.strip().lower() not in (geo[2] or "").lower():
        report["note"] = f"resolved to a different place: {geo[2]!r}"

    # Stage 3 -- POI provider
    raw = destination_search(destination)
    report["provider"] = raw.get("source")
    report["pois_returned"] = raw.get("results_count", 0)
    if not raw.get("activities"):
        report["stage_failed"] = "poi_provider: zero results"
        return report

    # Stage 4 -- conversion to scheduler candidates (drops missing coords/names)
    candidates, _ = _fetch_candidates(destination, raw)
    report["candidates_usable"] = len(candidates)
    report["dropped_in_conversion"] = raw.get("results_count", 0) - len(candidates)
    if not candidates:
        report["stage_failed"] = "candidate_conversion: all dropped (missing coords/name)"
        return report

    costs = sorted(c.estimated_cost for c in candidates)
    report["cheapest_candidate_cost"] = costs[0]

    # Stage 5 -- does the budget admit anything?
    req = ItineraryRequest(destination=destination, days=reqs.days or 3, activities_budget=None)
    response = generate_itinerary(req, raw)
    unbudgeted = sum(len(d.slots) for d in response.itinerary)
    report["slots_with_no_budget_cap"] = unbudgeted
    if unbudgeted == 0:
        report["stage_failed"] = "scheduler: nothing fits even without a budget cap"
        report["note"] = "likely travel-time or day-window constraint, not money"
        return report

    report["stage_failed"] = None
    report["conclusion"] = (
        "candidates exist and schedule fine without a cap -- if the full run produced "
        "zero stops, the budget allocation is the binding constraint"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default=None, help="diagnose one case by name")
    args = parser.parse_args()

    cases = [c for c in CASES if args.case is None or c.name == args.case]
    if not cases:
        print(f"no case named {args.case!r}")
        return 1

    results: List[Dict[str, Any]] = []
    for case in cases:
        try:
            report = _diagnose(case)
        except Exception as e:
            report = {"case": case.name, "stage_failed": f"crashed: {type(e).__name__}: {e}"}
        results.append(report)

        print(f"\n=== {report['case']} ===", flush=True)
        for key, value in report.items():
            if key != "case":
                print(f"  {key}: {value}")

    print("\n--- summary of failing stages ---")
    for report in results:
        if report.get("stage_failed"):
            print(f"  {report['case']:<26} {report['stage_failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
