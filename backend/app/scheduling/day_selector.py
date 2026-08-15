import math
from itertools import permutations
from typing import List, Optional, Tuple

from app.scheduling.models import Candidate, Coordinates, DaySchedule, ScheduleConstraints, ScheduledSlot
from app.scheduling.ports import TravelTimeProvider


def _tie_break_key(candidates: List[Candidate], indices: Tuple[int, ...]) -> Tuple[str, ...]:
    """Canonical, input-order-independent tie-break key for a set of chosen
    candidate indices: the sorted tuple of their names. Two combinations with
    equal total rating always compare via this key rather than via dict/insertion
    order, so `_knapsack_select`'s result depends only on which candidates were
    chosen -- never on the order the caller happened to pass them in."""
    return tuple(sorted(candidates[i].name for i in indices))


def _knapsack_select(candidates: List[Candidate], budget: float, max_items: int) -> List[Candidate]:
    """0/1 knapsack: maximize total rating, weight = estimated_cost, capacity =
    budget, additionally capped at max_items. Exact DP over (count, cost_used_cents)
    states -- small in practice since candidate pools and slot counts are both small.

    Ties (multiple combinations reaching the same maximum rating) are broken
    deterministically by `_tie_break_key`, not by input order."""
    if not candidates or max_items <= 0:
        return []

    # Quantization must be *conservative in both directions*, or budget enforcement
    # is unsound: the knapsack reasons in integer cents but the caller charges the
    # true float cost. Round the budget DOWN and each cost UP so the selected set's
    # true total can never exceed the real budget. (Found by the property test: a
    # 0.0039 cost round()ed to 0 cents looked free, got selected against a 0.0
    # budget, then charged its true cost to the trip total.)
    budget_cents = 10**9 if budget == float("inf") else max(math.floor(budget * 100), 0)
    costs_cents = [max(math.ceil(c.estimated_cost * 100), 0) for c in candidates]

    # states: (count_used, cost_used_cents) -> (total_rating, indices_tuple)
    states = {(0, 0): (0.0, ())}
    for i, cost in enumerate(costs_cents):
        rating = candidates[i].rating
        new_states = dict(states)
        for (count, used), (value, indices) in states.items():
            if count >= max_items:
                continue
            new_used = used + cost
            if new_used > budget_cents:
                continue
            key = (count + 1, new_used)
            new_value = value + rating
            new_indices = indices + (i,)
            existing = new_states.get(key)
            if existing is None or new_value > existing[0] or (
                new_value == existing[0]
                and _tie_break_key(candidates, new_indices) < _tie_break_key(candidates, existing[1])
            ):
                new_states[key] = (new_value, new_indices)
        states = new_states

    best_value = -1.0
    best_indices: Tuple[int, ...] = ()
    for value, indices in states.values():
        if value > best_value or (
            value == best_value
            and _tie_break_key(candidates, indices) < _tie_break_key(candidates, best_indices)
        ):
            best_value = value
            best_indices = indices

    return [candidates[i] for i in best_indices]


def _best_ordering(
    selected: List[Candidate],
    start: Optional[Coordinates],
    day_start_min: int,
    day_end_min: int,
    visit_duration_min: int,
    travel_provider: TravelTimeProvider,
) -> Optional[List[Tuple[Candidate, float]]]:
    """Try every ordering of `selected`, return the one with the earliest finish
    time that still fits within day_end_min, as a list of (candidate, travel_minutes
    from the previous stop). Ties break on lexicographic stop-name order for
    determinism. Returns None if no ordering fits, or [] if selected is empty."""
    if not selected:
        return []

    best_key = None
    best_ordering: Optional[List[Tuple[Candidate, float]]] = None

    for perm in permutations(selected):
        clock = float(day_start_min)
        prev_coords = start
        ordered_with_travel: List[Tuple[Candidate, float]] = []
        for candidate in perm:
            travel = travel_provider.minutes_between(prev_coords, candidate.coords) if prev_coords is not None else 0.0
            clock += travel + visit_duration_min
            ordered_with_travel.append((candidate, travel))
            prev_coords = candidate.coords

        if clock > day_end_min:
            continue

        key = (clock, tuple(c.name for c in perm))
        if best_key is None or key < best_key:
            best_key = key
            best_ordering = ordered_with_travel

    return best_ordering


def select_day(
    day: int,
    pool: List[Candidate],
    remaining_budget: Optional[float],
    constraints: ScheduleConstraints,
    travel_provider: TravelTimeProvider,
) -> Tuple[DaySchedule, float]:
    """
    Select and order stops for one day from `pool` (already filtered by the caller
    to exclude names used on previous days). Shrinks the slot count until an
    ordering fits the day's time window, or gives up with an explanatory note.
    Returns the DaySchedule and the budget actually spent (the caller subtracts
    this from the running trip total).
    """
    # _best_ordering brute-forces every permutation of the selected slots, i.e.
    # O(max_slots_per_day!). 6! = 720 is still effectively instant per day; this
    # bound exists purely to fail loudly if a future caller (e.g. request input)
    # ever lets max_slots_per_day grow unbounded, rather than silently hanging.
    assert constraints.max_slots_per_day <= 6, "max_slots_per_day too large for brute-force ordering (must be <= 6)"

    budget_for_knapsack = remaining_budget if remaining_budget is not None else float("inf")

    ordering: Optional[List[Tuple[Candidate, float]]] = None
    max_items = constraints.max_slots_per_day
    while max_items > 0:
        selected = _knapsack_select(pool, budget_for_knapsack, max_items)
        ordering = _best_ordering(
            selected,
            constraints.start_location,
            constraints.day_start_min,
            constraints.day_end_min,
            constraints.visit_duration_min,
            travel_provider,
        )
        if ordering:
            break
        max_items -= 1

    notes: List[str] = []
    if not ordering:
        ordering = []
        if pool:
            notes.append("no combination of available attractions fit within the time/budget limits")
        else:
            notes.append("no verified points of interest available to schedule")

    slots: List[ScheduledSlot] = []
    clock = float(constraints.day_start_min)
    spent = 0.0
    for slot_index, (candidate, travel) in enumerate(ordering):
        clock += travel
        start_min = int(round(clock))
        clock += constraints.visit_duration_min
        end_min = int(round(clock))
        spent += candidate.estimated_cost
        slots.append(ScheduledSlot(
            day=day,
            slot_index=slot_index,
            start_min=start_min,
            end_min=end_min,
            name=candidate.name,
            category=candidate.category,
            source=candidate.source,
            travel_min_from_previous=round(travel, 1),
            estimated_cost=candidate.estimated_cost,
        ))

    if 0 < len(slots) < constraints.max_slots_per_day:
        notes.append(f"left partially open — only {len(slots)} suitable stop(s) found within constraints")

    return DaySchedule(day=day, slots=slots, notes=notes), spent
