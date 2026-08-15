"""Hard-constraint verification.

The verifier owns correctness, so these tests are the ones that must never be relaxed
to make something else pass. Each violation type is asserted separately because the
repair step branches on the code, not the message.
"""
from app.schemas.trip import (
    BudgetBreakdown, DayPlan, Itinerary, ScheduledStop, TripRequirements,
)
from app.verification.plan_verifier import (
    ACTIVITIES_OVERSPEND, BUDGET_OVERRUN, DAY_COUNT_MISMATCH, STOP_OVERLAP,
    UNGROUNDED_FACT, verify_plan,
)


def _stop(name="Real Place", start="09:00", end="11:00", cost=10.0, source="overpass"):
    return ScheduledStop(
        name=name, category="historic", start_time=start, end_time=end,
        travel_minutes_from_previous=0.0, estimated_cost=cost, source=source,
    )


def _itinerary(days=1, stops_per_day=None):
    stops_per_day = stops_per_day or [[_stop()] for _ in range(days)]
    return Itinerary(
        destination="Testville",
        days=[DayPlan(day=i + 1, narrative="n", stops=stops_per_day[i]) for i in range(days)],
    )


def _budget(total=1000.0, activities=100.0):
    return BudgetBreakdown(transport=0, lodging=0, food=0,
                           activities=activities, buffer=0, total=total)


def test_well_formed_plan_passes():
    result = verify_plan(TripRequirements(destination="T", days=1, budget=2000.0),
                         _budget(), _itinerary())
    assert result.valid and result.violations == []


def test_budget_overrun_is_flagged_with_the_amount():
    result = verify_plan(TripRequirements(destination="T", days=1, budget=500.0),
                         _budget(total=800.0), _itinerary())
    overrun = [v for v in result.violations if v.code == BUDGET_OVERRUN]
    assert len(overrun) == 1
    assert overrun[0].overspend == 300.0
    assert overrun[0].repairable


def test_no_stated_budget_means_no_ceiling_to_violate():
    result = verify_plan(TripRequirements(destination="T", days=1, budget=None),
                         _budget(total=999999.0), _itinerary())
    assert result.valid


def test_day_count_mismatch_is_not_repairable():
    """The scheduler guarantees one day per requested day, so this means an upstream
    bug -- retrying the same pipeline would produce the identical result."""
    result = verify_plan(TripRequirements(destination="T", days=5), _budget(), _itinerary(days=2))
    mismatch = [v for v in result.violations if v.code == DAY_COUNT_MISMATCH]
    assert mismatch and not mismatch[0].repairable


def test_overlapping_stops_are_flagged():
    overlapping = [[_stop(name="A", start="09:00", end="12:00"),
                    _stop(name="B", start="11:00", end="13:00")]]
    result = verify_plan(TripRequirements(destination="T", days=1),
                         _budget(), _itinerary(1, overlapping))
    assert any(v.code == STOP_OVERLAP for v in result.violations)


def test_a_stop_without_attribution_fails_verification():
    """This is what makes "nothing is invented" enforceable rather than aspirational."""
    ungrounded = [[_stop(name="Invented Place", source="")]]
    result = verify_plan(TripRequirements(destination="T", days=1),
                         _budget(), _itinerary(1, ungrounded))
    assert any(v.code == UNGROUNDED_FACT for v in result.violations)
    assert not result.valid


def test_activities_overspend_is_flagged_and_repairable():
    pricey = [[_stop(name="Pricey", cost=500.0)]]
    result = verify_plan(TripRequirements(destination="T", days=1),
                         _budget(activities=100.0), _itinerary(1, pricey))
    overspend = [v for v in result.violations if v.code == ACTIVITIES_OVERSPEND]
    assert overspend and overspend[0].repairable


def test_all_violations_are_reported_not_just_the_first():
    """The repair step needs the whole picture before deciding what to change."""
    bad = [[_stop(name="X", cost=999.0, source=""), _stop(name="Y", start="09:30", end="10:00")]]
    result = verify_plan(TripRequirements(destination="T", days=1, budget=1.0),
                         _budget(total=800.0, activities=1.0), _itinerary(1, bad))
    codes = {v.code for v in result.violations}
    assert len(codes) >= 3


def test_rounding_noise_is_not_an_overrun():
    result = verify_plan(TripRequirements(destination="T", days=1, budget=1000.0),
                         _budget(total=1000.005), _itinerary())
    assert result.valid
