"""Build a day-by-day itinerary.

The scheduler decides everything structural: which real place goes in which slot, in
what order, at what time, under the budget ceiling. Narration is templated prose over
an already-fixed schedule. There is no code path where a language model chooses,
reorders, renames, or invents a stop -- that separation is the point of the design, and
it is what makes every stop traceable to a lookup.
"""
import logging
from typing import List, Optional, Tuple

from app.schemas.trip import DayPlan, Itinerary, ScheduledStop
from app.scheduling.costs import StaticCostEstimator
from app.scheduling.geo import HaversineTravelTimeProvider
from app.scheduling.models import Candidate, Coordinates, ScheduleConstraints, ScheduleResult
from app.scheduling.scheduler import build_schedule
from app.scheduling.validator import validate
from app.tools.destination_search import destination_search

logger = logging.getLogger("app.agents.itinerary")


def _to_candidates(activities: List[dict], source: str) -> List[Candidate]:
    estimator = StaticCostEstimator()
    candidates: List[Candidate] = []
    for item in activities:
        lat, lon = item.get("lat"), item.get("lon")
        if lat is None or lon is None:
            # Skipped rather than defaulted to (0,0), which would silently place the
            # stop in the Gulf of Guinea and corrupt every travel-time calculation.
            continue
        category = item.get("category", "attraction")
        cost = item.get("estimated_cost")
        if cost is None:
            # Never zero. An unpriced stop treated as free slips past the budget ceiling.
            cost = estimator.estimate(category)
        candidates.append(Candidate(
            name=item["name"], category=category,
            rating=float(item.get("rating", 3.0)),
            coords=Coordinates(lat=lat, lon=lon),
            source=source, estimated_cost=float(cost),
        ))
    return candidates


def _minutes_to_hhmm(minutes: float) -> str:
    total = int(round(minutes)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _narrate(stops: List[ScheduledStop]) -> str:
    if not stops:
        return "No verified attractions were available for this day."
    parts = [f"{s.name} ({s.start_time}–{s.end_time})" for s in stops]
    return "Visiting " + ", then ".join(parts) + "."


def build_itinerary(
    destination: str,
    days: int,
    activities_budget: Optional[float] = None,
    start_coords: Optional[Tuple[float, float]] = None,
    prefetched: Optional[dict] = None,
) -> Itinerary:
    lookup = prefetched if prefetched is not None else destination_search(destination)
    activities = lookup.get("activities", [])
    source = lookup.get("source") or "unknown"
    resolved = lookup.get("resolved_location")

    candidates = _to_candidates(activities, source)

    constraints = ScheduleConstraints(
        days=max(days, 1),
        start_location=Coordinates(*start_coords) if start_coords else None,
        activities_budget=activities_budget,
    )
    result: ScheduleResult = build_schedule(
        candidates, constraints, HaversineTravelTimeProvider()
    )

    # Trust-but-verify over the scheduler's own logic. A violation here is a bug in the
    # scheduler, not in the request, so it is logged loudly rather than surfaced as a
    # user-facing warning.
    check = validate(result, constraints)
    if not check.valid:
        logger.error("Scheduler produced an invalid result for %r: %s",
                     destination, check.violations)

    warnings: List[str] = []
    if resolved:
        # Always name the place that was actually planned. A substring check is not
        # enough: "Goa" IS a substring of "Goa, Philippines", so the single most
        # dangerous case -- right name, wrong country -- would pass silently. There is
        # no way to infer intent from the string alone, so the honest move is to state
        # the resolution every time and let the reader catch a mismatch.
        leading = resolved.split(",")[0].strip().lower()
        if leading != destination.strip().lower():
            warnings.append(
                f"'{destination}' resolved to '{resolved}' — the stops below are in "
                f"{resolved}, which may not be the place you meant."
            )
        else:
            warnings.append(f"Planned for {resolved}.")
    warnings.extend(result.warnings)

    day_plans: List[DayPlan] = []
    for day_schedule in result.days:
        stops = [
            ScheduledStop(
                name=slot.name, category=slot.category,
                start_time=_minutes_to_hhmm(slot.start_min),
                end_time=_minutes_to_hhmm(slot.end_min),
                travel_minutes_from_previous=slot.travel_min_from_previous,
                estimated_cost=slot.estimated_cost, source=slot.source,
            )
            for slot in day_schedule.slots
        ]
        day_plans.append(DayPlan(day=day_schedule.day, narrative=_narrate(stops), stops=stops))

    return Itinerary(
        destination=destination, resolved_location=resolved,
        days=day_plans, warnings=warnings,
    )
