from app.scheduling.models import Candidate, Coordinates, ScheduleConstraints
from app.scheduling.geo import HaversineTravelTimeProvider
from app.scheduling.day_selector import _knapsack_select, _best_ordering, select_day

ALPHA = Candidate(name="Alpha Fort", category="historic", rating=5.0, coords=Coordinates(0.0, 0.0), source="test", estimated_cost=10.0)
BETA = Candidate(name="Beta Garden", category="natural", rating=4.0, coords=Coordinates(0.0, 0.01), source="test", estimated_cost=10.0)
GAMMA = Candidate(name="Gamma Point", category="natural", rating=3.0, coords=Coordinates(0.0, 5.0), source="test", estimated_cost=10.0)
DELTA = Candidate(name="Delta Museum", category="museums", rating=4.5, coords=Coordinates(0.0, 0.02), source="test", estimated_cost=100.0)


def test_knapsack_select_picks_highest_value_combo_within_budget_and_slot_cap():
    selected = _knapsack_select([ALPHA, BETA, GAMMA, DELTA], budget=25.0, max_items=2)
    assert {c.name for c in selected} == {"Alpha Fort", "Beta Garden"}


def test_knapsack_select_excludes_items_that_alone_exceed_budget():
    selected = _knapsack_select([DELTA], budget=25.0, max_items=1)
    assert selected == []


def test_knapsack_select_respects_unlimited_budget():
    selected = _knapsack_select([ALPHA, BETA, GAMMA, DELTA], budget=float("inf"), max_items=4)
    assert {c.name for c in selected} == {"Alpha Fort", "Beta Garden", "Gamma Point", "Delta Museum"}


def test_knapsack_select_tie_break_is_input_order_independent():
    # Three candidates with identical rating and cost: every 2-item combination
    # ties on total value, so the result must come from the name-based tie-break
    # (smallest sorted-name pair wins), not from whatever order the caller passed
    # them in.
    x = Candidate(name="X", category="misc", rating=3.0, coords=Coordinates(0.0, 0.0), source="test", estimated_cost=10.0)
    y = Candidate(name="Y", category="misc", rating=3.0, coords=Coordinates(0.0, 0.01), source="test", estimated_cost=10.0)
    z = Candidate(name="Z", category="misc", rating=3.0, coords=Coordinates(0.0, 0.02), source="test", estimated_cost=10.0)

    for ordering in ([x, y, z], [y, z, x], [z, x, y], [z, y, x]):
        selected = _knapsack_select(ordering, budget=20.0, max_items=2)
        assert {c.name for c in selected} == {"X", "Y"}


def test_best_ordering_ties_break_lexicographically_by_name():
    ordering = _best_ordering(
        [BETA, ALPHA],
        start=None,
        day_start_min=540,
        day_end_min=1260,
        visit_duration_min=120,
        travel_provider=HaversineTravelTimeProvider(speed_kmh=20.0),
    )
    names = [c.name for c, _ in ordering]
    assert names == ["Alpha Fort", "Beta Garden"]


def test_best_ordering_returns_none_when_nothing_fits_within_day_end():
    ordering = _best_ordering(
        [ALPHA, BETA, GAMMA],
        start=None,
        day_start_min=540,
        day_end_min=560,
        visit_duration_min=120,
        travel_provider=HaversineTravelTimeProvider(speed_kmh=20.0),
    )
    assert ordering is None


def test_select_day_shrinks_slot_count_when_day_is_too_short_for_full_slate():
    constraints = ScheduleConstraints(days=1, day_start_min=540, day_end_min=700, visit_duration_min=120, max_slots_per_day=2)
    day_schedule, spent = select_day(
        day=1, pool=[ALPHA, BETA], remaining_budget=None, constraints=constraints,
        travel_provider=HaversineTravelTimeProvider(speed_kmh=20.0),
    )
    assert len(day_schedule.slots) == 1
    assert day_schedule.slots[0].name == "Alpha Fort"
    assert spent == 10.0
    assert any("left partially open" in note for note in day_schedule.notes)


def test_select_day_returns_empty_with_note_when_pool_is_empty():
    constraints = ScheduleConstraints(days=1)
    day_schedule, spent = select_day(
        day=1, pool=[], remaining_budget=None, constraints=constraints,
        travel_provider=HaversineTravelTimeProvider(speed_kmh=20.0),
    )
    assert day_schedule.slots == []
    assert spent == 0.0
    assert any("no verified points of interest" in note.lower() for note in day_schedule.notes)


def test_select_day_returns_empty_with_note_when_day_too_short_for_any_single_visit():
    # Distinct from the empty-pool case: the pool is non-empty, but the day
    # window is too short to fit even one visit, so the shrink loop bottoms out
    # at max_items == 0 and select_day must still return gracefully.
    constraints = ScheduleConstraints(days=1, day_start_min=540, day_end_min=550, visit_duration_min=120, max_slots_per_day=2)
    day_schedule, spent = select_day(
        day=1, pool=[ALPHA, BETA], remaining_budget=None, constraints=constraints,
        travel_provider=HaversineTravelTimeProvider(speed_kmh=20.0),
    )
    assert day_schedule.slots == []
    assert spent == 0.0
    assert any("no combination" in note.lower() and "fit" in note.lower() for note in day_schedule.notes)


def test_select_day_populates_slot_times_and_travel():
    constraints = ScheduleConstraints(days=1, day_start_min=540, day_end_min=1260, visit_duration_min=120, max_slots_per_day=2)
    day_schedule, spent = select_day(
        day=1, pool=[ALPHA, BETA], remaining_budget=100.0, constraints=constraints,
        travel_provider=HaversineTravelTimeProvider(speed_kmh=20.0),
    )
    assert len(day_schedule.slots) == 2
    first, second = day_schedule.slots
    assert first.start_min == 540
    assert first.end_min == 660
    assert second.start_min >= first.end_min
    assert spent == 20.0
