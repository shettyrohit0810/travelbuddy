from app.scheduling.models import DaySchedule, ScheduleConstraints, ScheduledSlot, ScheduleResult
from app.scheduling.validator import validate


def _slot(name, start_min, end_min, cost=10.0):
    return ScheduledSlot(
        day=1, slot_index=0, start_min=start_min, end_min=end_min,
        name=name, category="historic", source="test",
        travel_min_from_previous=0.0, estimated_cost=cost,
    )


def test_validate_accepts_a_well_formed_schedule():
    day = DaySchedule(day=1, slots=[_slot("X", 540, 660)])
    result = ScheduleResult(days=[day], total_estimated_cost=10.0)
    constraints = ScheduleConstraints(days=1, activities_budget=100.0)
    v = validate(result, constraints)
    assert v.valid
    assert v.violations == []


def test_validate_flags_overlapping_slots():
    day = DaySchedule(day=1, slots=[_slot("X", 540, 660), _slot("Y", 600, 720)])
    result = ScheduleResult(days=[day], total_estimated_cost=20.0)
    constraints = ScheduleConstraints(days=1)
    v = validate(result, constraints)
    assert not v.valid
    assert any("overlaps" in msg for msg in v.violations)


def test_validate_flags_slot_starting_before_day_start():
    day = DaySchedule(day=1, slots=[_slot("X", 500, 620)])
    result = ScheduleResult(days=[day], total_estimated_cost=10.0)
    constraints = ScheduleConstraints(days=1, day_start_min=540)
    v = validate(result, constraints)
    assert not v.valid
    assert any("day_start_min" in msg for msg in v.violations)


def test_validate_flags_slot_ending_after_day_end():
    day = DaySchedule(day=1, slots=[_slot("X", 1200, 1300)])
    result = ScheduleResult(days=[day], total_estimated_cost=10.0)
    constraints = ScheduleConstraints(days=1, day_end_min=1260)
    v = validate(result, constraints)
    assert not v.valid
    assert any("day_end_min" in msg for msg in v.violations)


def test_validate_flags_budget_overrun():
    day = DaySchedule(day=1, slots=[_slot("X", 540, 660, cost=999.0)])
    result = ScheduleResult(days=[day], total_estimated_cost=999.0)
    constraints = ScheduleConstraints(days=1, activities_budget=100.0)
    v = validate(result, constraints)
    assert not v.valid
    assert any("exceeds activities_budget" in msg for msg in v.violations)


def test_validate_ignores_budget_when_none_given():
    day = DaySchedule(day=1, slots=[_slot("X", 540, 660, cost=999.0)])
    result = ScheduleResult(days=[day], total_estimated_cost=999.0)
    constraints = ScheduleConstraints(days=1, activities_budget=None)
    v = validate(result, constraints)
    assert v.valid
