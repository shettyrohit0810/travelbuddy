"""The verify → repair cycle.

Termination is the property that matters most: an unbounded repair loop is a cost
incident with extra steps. Every exit condition is asserted separately.
"""
import pytest

from app.agents.orchestrator import (
    MAX_REPAIR_ATTEMPTS, REPAIR_FLOORS, REPAIR_LEVERS, _headroom,
    repair_node, verification_node, verification_router,
)
from app.schemas.trip import (
    BudgetBreakdown, DayPlan, Itinerary, ScheduledStop, TripRequirements,
)
from app.verification.plan_verifier import BUDGET_OVERRUN, VerificationResult, Violation


def _budget(transport=400.0, lodging=200.0, food=100.0, activities=300.0, total=1000.0):
    return BudgetBreakdown(transport=transport, lodging=lodging, food=food,
                           activities=activities, buffer=0.0, total=total)


def _itinerary(days=1):
    return Itinerary(destination="T", days=[
        DayPlan(day=i + 1, narrative="n", stops=[ScheduledStop(
            name="Real", category="historic", start_time="09:00", end_time="11:00",
            travel_minutes_from_previous=0.0, estimated_cost=10.0, source="overpass",
        )]) for i in range(days)
    ])


def _overrun(amount):
    return VerificationResult(valid=False, violations=[
        Violation(BUDGET_OVERRUN, "over", repairable=True, overspend=amount)
    ])


# --- routing ------------------------------------------------------------------

def test_valid_plan_goes_straight_to_assemble():
    assert verification_router({"verification": VerificationResult(valid=True)}) == "assemble"


def test_repairable_violation_dispatches_a_repair():
    state = {"verification": _overrun(100.0), "repair_attempts": 0, "budget": _budget()}
    assert verification_router(state) == "repair"


def test_unrepairable_violation_is_not_retried():
    verification = VerificationResult(valid=False, violations=[
        Violation("ungrounded_fact", "x", repairable=False)
    ])
    assert verification_router({"verification": verification, "repair_attempts": 0}) == "assemble"


def test_attempt_cap_terminates_the_loop():
    state = {"verification": _overrun(100.0), "repair_attempts": MAX_REPAIR_ATTEMPTS,
             "budget": _budget()}
    assert verification_router(state) == "assemble"


def test_exhausted_headroom_short_circuits_before_dispatching():
    """Catching this in the router saves re-running the whole scheduler to reach an
    identical plan."""
    floored = BudgetBreakdown(
        transport=400.0 * REPAIR_FLOORS["transport"], lodging=200.0 * REPAIR_FLOORS["lodging"],
        food=100.0 * REPAIR_FLOORS["food"], activities=0.0, buffer=0.0, total=0.0,
    )
    state = {"verification": _overrun(9000.0), "repair_attempts": 0,
             "budget": floored, "budget_baseline": _budget()}
    assert _headroom(floored, _budget()) == pytest.approx(0.0)
    assert verification_router(state) == "assemble"


# --- repair mechanics ---------------------------------------------------------

def test_activities_absorb_a_small_overrun_before_anything_else():
    out = repair_node({"verification": _overrun(100.0), "budget": _budget(),
                       "repair_attempts": 0, "logs": []})
    assert out["budget"].activities == 200.0
    assert out["budget"].food == 100.0      # untouched
    assert out["budget"].lodging == 200.0   # untouched
    assert out["budget"].transport == 400.0 # untouched


def test_large_overrun_cascades_through_the_lever_order():
    out = repair_node({"verification": _overrun(500.0), "budget": _budget(),
                       "repair_attempts": 0, "logs": []})
    budget = out["budget"]
    assert budget.activities == 0.0
    assert budget.food < 100.0
    assert budget.total < 1000.0


def test_transport_is_reduced_only_after_everything_else_is_floored():
    """Transport maps to a concrete priced option, so writing it down is closest to
    lying about the price -- it goes last and keeps the highest floor."""
    out = repair_node({"verification": _overrun(99999.0), "budget": _budget(),
                       "repair_attempts": 0, "logs": []})
    budget = out["budget"]
    assert budget.activities == 0.0
    assert budget.transport == pytest.approx(400.0 * REPAIR_FLOORS["transport"])
    assert budget.transport > 0
    assert REPAIR_LEVERS[-1] == "transport"


def test_floors_are_never_breached():
    out = repair_node({"verification": _overrun(99999.0), "budget": _budget(),
                       "repair_attempts": 0, "logs": []})
    budget = out["budget"]
    assert budget.food == pytest.approx(100.0 * REPAIR_FLOORS["food"])
    assert budget.lodging == pytest.approx(200.0 * REPAIR_FLOORS["lodging"])
    assert budget.food > 0 and budget.lodging > 0


def test_floors_anchor_to_the_baseline_so_the_loop_terminates():
    """Guards a Zeno bug: floors taken from the CURRENT value let each pass shave
    another fraction, approaching zero without ever reaching a floor."""
    baseline = _budget()
    first = repair_node({"verification": _overrun(99999.0), "budget": baseline,
                         "repair_attempts": 0, "logs": []})
    second = repair_node({"verification": _overrun(99999.0), "budget": first["budget"],
                          "budget_baseline": baseline, "repair_attempts": 1, "logs": []})
    assert second["budget"].food == first["budget"].food
    assert second["budget"].transport == first["budget"].transport
    assert second["repair_exhausted"] is True


def test_repair_recomputes_the_total_from_its_parts():
    out = repair_node({"verification": _overrun(100.0), "budget": _budget(),
                       "repair_attempts": 0, "logs": []})
    budget = out["budget"]
    assert budget.total == pytest.approx(
        budget.transport + budget.lodging + budget.food + budget.activities + budget.buffer
    )


# --- end to end on the loop's logic -------------------------------------------

def test_one_repair_pass_resolves_a_fixable_overrun():
    requirements = TripRequirements(destination="T", days=1, budget=900.0)
    state = {"requirements": requirements, "budget": _budget(), "itinerary": _itinerary(), "logs": []}

    first = verification_node(state)
    assert not first["verification"].valid

    state["verification"] = first["verification"]
    repaired = repair_node({**state, "repair_attempts": 0})
    state["budget"] = repaired["budget"]

    assert verification_node(state)["verification"].valid


def test_impossible_budget_terminates_and_reports_honestly():
    requirements = TripRequirements(destination="T", days=1, budget=50.0)
    state = {"requirements": requirements, "budget": _budget(), "itinerary": _itinerary(),
             "logs": [], "repair_attempts": 0}

    for _ in range(MAX_REPAIR_ATTEMPTS + 2):
        verification = verification_node(state)["verification"]
        state["verification"] = verification
        if verification_router(state) == "assemble":
            break
        repaired = repair_node(state)
        state.update(budget=repaired["budget"], budget_baseline=repaired["budget_baseline"],
                     repair_attempts=repaired["repair_attempts"],
                     repair_exhausted=repaired["repair_exhausted"])

    assert not state["verification"].valid          # reported, not faked
    assert state["repair_attempts"] <= MAX_REPAIR_ATTEMPTS
