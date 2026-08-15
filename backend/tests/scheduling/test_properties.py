import string

from hypothesis import given, settings as hyp_settings, strategies as st

from app.scheduling.models import Candidate, Coordinates, ScheduleConstraints
from app.scheduling.geo import HaversineTravelTimeProvider
from app.scheduling.scheduler import build_schedule
from app.scheduling.validator import validate

PROVIDER = HaversineTravelTimeProvider(speed_kmh=20.0)


def _candidate_strategy():
    return st.builds(
        Candidate,
        name=st.text(alphabet=string.ascii_letters, min_size=1, max_size=12),
        category=st.sampled_from(["historic", "museums", "natural", "cultural"]),
        rating=st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        coords=st.builds(
            Coordinates,
            lat=st.floats(min_value=-60.0, max_value=60.0, allow_nan=False, allow_infinity=False),
            lon=st.floats(min_value=-170.0, max_value=170.0, allow_nan=False, allow_infinity=False),
        ),
        source=st.just("test"),
        estimated_cost=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        open_windows=st.none(),
        mandatory=st.just(False),
    )


@given(
    candidates=st.lists(_candidate_strategy(), min_size=0, max_size=15, unique_by=lambda c: c.name),
    days=st.integers(min_value=1, max_value=5),
    budget=st.one_of(st.none(), st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False)),
)
@hyp_settings(max_examples=100)
def test_build_schedule_never_violates_constraints(candidates, days, budget):
    constraints = ScheduleConstraints(days=days, activities_budget=budget)
    result = build_schedule(candidates, constraints, PROVIDER)
    validation = validate(result, constraints)
    assert validation.valid, validation.violations


@given(
    candidates=st.lists(_candidate_strategy(), min_size=0, max_size=15, unique_by=lambda c: c.name),
    days=st.integers(min_value=1, max_value=5),
)
@hyp_settings(max_examples=50)
def test_build_schedule_is_deterministic(candidates, days):
    constraints = ScheduleConstraints(days=days)
    result1 = build_schedule(candidates, constraints, PROVIDER)
    result2 = build_schedule(candidates, constraints, PROVIDER)
    assert result1 == result2


@given(
    candidates=st.lists(_candidate_strategy(), min_size=0, max_size=15, unique_by=lambda c: c.name),
    days=st.integers(min_value=1, max_value=5),
)
@hyp_settings(max_examples=50)
def test_build_schedule_always_returns_exactly_one_day_schedule_per_day(candidates, days):
    constraints = ScheduleConstraints(days=days)
    result = build_schedule(candidates, constraints, PROVIDER)
    assert [d.day for d in result.days] == list(range(1, days + 1))
