from app.scheduling.models import Candidate, Coordinates, ScheduleConstraints
from app.scheduling.geo import HaversineTravelTimeProvider
from app.scheduling.scheduler import build_schedule

ALPHA = Candidate(name="Alpha Fort", category="historic", rating=5.0, coords=Coordinates(0.0, 0.0), source="test", estimated_cost=10.0)
BETA = Candidate(name="Beta Garden", category="natural", rating=4.0, coords=Coordinates(0.0, 0.01), source="test", estimated_cost=10.0)
GAMMA = Candidate(name="Gamma Point", category="natural", rating=3.0, coords=Coordinates(0.0, 5.0), source="test", estimated_cost=10.0)

PROVIDER = HaversineTravelTimeProvider(speed_kmh=20.0)


def test_build_schedule_produces_one_day_schedule_per_requested_day():
    constraints = ScheduleConstraints(days=3)
    result = build_schedule([ALPHA, BETA, GAMMA], constraints, PROVIDER)
    assert len(result.days) == 3
    assert [d.day for d in result.days] == [1, 2, 3]


def test_build_schedule_does_not_repeat_a_candidate_while_unused_ones_remain():
    constraints = ScheduleConstraints(days=2, max_slots_per_day=1)
    result = build_schedule([ALPHA, BETA], constraints, PROVIDER)
    day1_names = {s.name for s in result.days[0].slots}
    day2_names = {s.name for s in result.days[1].slots}
    assert day1_names.isdisjoint(day2_names)
    assert day1_names | day2_names == {"Alpha Fort", "Beta Garden"}


def test_build_schedule_revisits_best_candidate_when_day_has_no_unused_options():
    constraints = ScheduleConstraints(days=2, max_slots_per_day=2)
    result = build_schedule([ALPHA], constraints, PROVIDER)
    assert result.days[0].slots[0].name == "Alpha Fort"
    assert result.days[1].slots[0].name == "Alpha Fort"
    assert any("Revisiting Alpha Fort" in w for w in result.warnings)


def test_build_schedule_with_no_candidates_returns_empty_days_with_warnings():
    constraints = ScheduleConstraints(days=2)
    result = build_schedule([], constraints, PROVIDER)
    assert all(d.slots == [] for d in result.days)
    assert len(result.warnings) == 2


def test_build_schedule_total_cost_matches_sum_of_slot_costs():
    constraints = ScheduleConstraints(days=1, max_slots_per_day=2)
    result = build_schedule([ALPHA, BETA], constraints, PROVIDER)
    slot_cost_sum = sum(s.estimated_cost for d in result.days for s in d.slots)
    assert result.total_estimated_cost == slot_cost_sum


def test_build_schedule_never_spends_more_than_a_sub_cent_budget():
    """Regression (found by hypothesis): costs are quantized to integer cents for
    the knapsack but charged at full float precision. A sub-cent cost must not be
    treated as free against a zero budget."""
    tiny = Candidate(
        name="Tiny", category="historic", rating=1.0,
        coords=Coordinates(0.0, 0.0), source="test", estimated_cost=0.00390625,
    )
    constraints = ScheduleConstraints(days=1, activities_budget=0.0)
    result = build_schedule([tiny], constraints, PROVIDER)
    assert result.total_estimated_cost <= 0.0


def test_build_schedule_depletes_budget_across_days():
    constraints = ScheduleConstraints(days=2, max_slots_per_day=1, activities_budget=10.0)
    result = build_schedule([ALPHA, BETA], constraints, PROVIDER)
    # Only enough budget (10.0) for exactly one 10.0-cost stop across the whole trip.
    total_slots = sum(len(d.slots) for d in result.days)
    assert total_slots == 1
    assert result.total_estimated_cost == 10.0
