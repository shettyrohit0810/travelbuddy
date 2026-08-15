from app.scheduling.models import (
    Coordinates,
    TimeWindow,
    Candidate,
    ScheduleConstraints,
    ScheduledSlot,
    DaySchedule,
    ScheduleResult,
)


def test_candidate_is_frozen():
    c = Candidate(
        name="Test Fort",
        category="historic",
        rating=4.5,
        coords=Coordinates(lat=1.0, lon=2.0),
        source="test",
        estimated_cost=10.0,
    )
    try:
        c.rating = 5.0
        assert False, "Candidate should be immutable"
    except AttributeError:
        pass


def test_candidate_defaults():
    c = Candidate(
        name="Test Fort",
        category="historic",
        rating=4.5,
        coords=Coordinates(lat=1.0, lon=2.0),
        source="test",
        estimated_cost=10.0,
    )
    assert c.open_windows is None
    assert c.mandatory is False


def test_schedule_constraints_defaults():
    constraints = ScheduleConstraints(days=3)
    assert constraints.day_start_min == 540
    assert constraints.day_end_min == 1260
    assert constraints.visit_duration_min == 120
    assert constraints.start_location is None
    assert constraints.activities_budget is None
    assert constraints.max_slots_per_day == 3


def test_day_schedule_and_result_default_lists():
    day = DaySchedule(day=1, slots=[])
    assert day.notes == []
    result = ScheduleResult(days=[day], total_estimated_cost=0.0)
    assert result.warnings == []


def test_time_window_and_scheduled_slot_construction():
    window = TimeWindow(start_min=540, end_min=600)
    assert window.start_min == 540
    slot = ScheduledSlot(
        day=1, slot_index=0, start_min=540, end_min=660,
        name="Test Fort", category="historic", source="test",
        travel_min_from_previous=5.0, estimated_cost=10.0,
    )
    assert slot.end_min == 660
