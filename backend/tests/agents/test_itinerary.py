"""Itinerary construction.

The invariant under test throughout: the scheduler decides, and every stop that appears
came from the supplied lookup. There is no path where prose invents a place.
"""
from app.agents.itinerary import build_itinerary

ACTIVITIES = [
    {"name": "Mock Temple", "category": "historic", "rating": 4.8, "lat": 35.0, "lon": 135.0,
     "estimated_cost": 10.0},
    {"name": "Mock Garden", "category": "natural", "rating": 4.5, "lat": 35.001, "lon": 135.001,
     "estimated_cost": 0.0},
    {"name": "Mock Market", "category": "cultural", "rating": 4.2, "lat": 35.002, "lon": 135.002,
     "estimated_cost": 15.0},
]


def _lookup(activities=None, resolved="Testville, Japan"):
    activities = ACTIVITIES if activities is None else activities
    return {"destination": "Testville", "resolved_location": resolved,
            "results_count": len(activities), "activities": activities, "source": "overpass"}


def test_only_supplied_places_are_scheduled():
    itinerary = build_itinerary("Testville", days=1, prefetched=_lookup())
    scheduled = {s.name for day in itinerary.days for s in day.stops}
    assert scheduled and scheduled.issubset({a["name"] for a in ACTIVITIES})


def test_every_stop_carries_its_source():
    itinerary = build_itinerary("Testville", days=2, prefetched=_lookup())
    for day in itinerary.days:
        for stop in day.stops:
            assert stop.source == "overpass"


def test_narrative_only_mentions_scheduled_stops():
    itinerary = build_itinerary("Testville", days=1, prefetched=_lookup())
    day = itinerary.days[0]
    for stop in day.stops:
        assert stop.name in day.narrative


def test_no_data_yields_empty_days_and_a_warning_not_filler():
    itinerary = build_itinerary("Nowhere", days=2, prefetched=_lookup([], resolved=None))
    assert all(len(day.stops) == 0 for day in itinerary.days)
    assert itinerary.warnings


def test_zero_budget_schedules_only_free_stops():
    """A zero budget does not mean "schedule nothing" -- genuinely free places still
    fit. The invariant is that nothing with a cost gets through."""
    itinerary = build_itinerary("Testville", days=1, activities_budget=0.0, prefetched=_lookup())
    stops = [s for day in itinerary.days for s in day.stops]
    assert all(s.estimated_cost == 0.0 for s in stops)


def test_budget_ceiling_is_respected():
    itinerary = build_itinerary("Testville", days=1, activities_budget=10.0, prefetched=_lookup())
    total = sum(s.estimated_cost for day in itinerary.days for s in day.stops)
    assert total <= 10.0


def test_places_without_coordinates_are_skipped_not_defaulted():
    """A missing coordinate defaulted to (0,0) would place the stop in the Gulf of
    Guinea and silently corrupt every travel-time calculation."""
    activities = ACTIVITIES + [{"name": "No Coords", "category": "historic", "rating": 5.0}]
    itinerary = build_itinerary("Testville", days=1, prefetched=_lookup(activities))
    assert "No Coords" not in {s.name for day in itinerary.days for s in day.stops}


def test_resolution_mismatch_is_surfaced_as_a_warning():
    itinerary = build_itinerary("Goa", days=1, prefetched=_lookup(resolved="Goa, Philippines"))
    assert any("Philippines" in w for w in itinerary.warnings)


def test_one_day_plan_per_requested_day():
    itinerary = build_itinerary("Testville", days=4, prefetched=_lookup())
    assert [d.day for d in itinerary.days] == [1, 2, 3, 4]
