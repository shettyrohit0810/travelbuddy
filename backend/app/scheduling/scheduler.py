from typing import List, Optional

from app.scheduling.models import Candidate, DaySchedule, ScheduleConstraints, ScheduleResult
from app.scheduling.day_selector import select_day
from app.scheduling.ports import TravelTimeProvider


def build_schedule(
    candidates: List[Candidate],
    constraints: ScheduleConstraints,
    travel_provider: TravelTimeProvider,
) -> ScheduleResult:
    """
    Build a day-by-day schedule. Deterministic: same candidates + constraints always
    produce the same result. Each candidate is used at most once across the trip
    unless the repeat-fallback kicks in (a day would otherwise be completely empty
    and at least one candidate exists trip-wide).
    """
    used_names: set = set()
    days: List[DaySchedule] = []
    total_spent = 0.0
    remaining_budget: Optional[float] = constraints.activities_budget
    warnings: List[str] = []

    for day in range(1, constraints.days + 1):
        pool = [c for c in candidates if c.name not in used_names]
        day_schedule, spent = select_day(day, pool, remaining_budget, constraints, travel_provider)

        if not day_schedule.slots and candidates:
            best_overall = max(candidates, key=lambda c: (c.rating, c.name))
            fallback_schedule, fallback_spent = select_day(
                day, [best_overall], remaining_budget, constraints, travel_provider
            )
            if fallback_schedule.slots:
                day_schedule = DaySchedule(
                    day=day,
                    slots=fallback_schedule.slots,
                    notes=[f"Revisiting {best_overall.name} — limited new options found nearby"],
                )
                spent = fallback_spent

        for slot in day_schedule.slots:
            used_names.add(slot.name)
        total_spent += spent
        if remaining_budget is not None:
            remaining_budget = max(remaining_budget - spent, 0.0)

        days.append(day_schedule)
        warnings.extend(f"Day {day}: {note}" for note in day_schedule.notes)

    return ScheduleResult(days=days, total_estimated_cost=total_spent, warnings=warnings)
