"""Budget allocation.

Splits a stated budget across categories, or derives one from costs when none was
stated. The allocation is arithmetic and auditable -- no model decides how much a trip
costs, because the verifier checks plans against these numbers and a hallucinated
figure inside the correctness layer defeats the whole design.
"""
from typing import List, Optional

from app.schemas.trip import BudgetBreakdown, TransportOption

# Shares of what remains after transport is paid for.
_FOOD_SHARE = 0.35
_LODGING_SHARE = 0.35
_ACTIVITIES_SHARE = 0.20
_BUFFER_SHARE = 0.10

_FOOD_PER_PERSON_PER_DAY = 900.0
_LODGING_PER_NIGHT = 2500.0


def build_budget(
    stated_budget: Optional[float],
    transport: List[TransportOption],
    days: int,
    travelers: int,
) -> BudgetBreakdown:
    transport_cost = min((t.estimated_cost for t in transport), default=0.0)
    days = max(days, 1)
    travelers = max(travelers, 1)

    if stated_budget is None:
        # No ceiling given: derive a plausible total from per-unit rates so the planner
        # still has an activities figure to schedule against.
        food = _FOOD_PER_PERSON_PER_DAY * days * travelers
        lodging = _LODGING_PER_NIGHT * max(days - 1, 1)
        activities = 500.0 * days * travelers
        buffer = (transport_cost + food + lodging + activities) * 0.10
        total = transport_cost + food + lodging + activities + buffer
        return BudgetBreakdown(
            transport=round(transport_cost, 2), lodging=round(lodging, 2),
            food=round(food, 2), activities=round(activities, 2),
            buffer=round(buffer, 2), total=round(total, 2),
        )

    remaining = max(stated_budget - transport_cost, 0.0)
    breakdown = BudgetBreakdown(
        transport=round(transport_cost, 2),
        lodging=round(remaining * _LODGING_SHARE, 2),
        food=round(remaining * _FOOD_SHARE, 2),
        activities=round(remaining * _ACTIVITIES_SHARE, 2),
        buffer=round(remaining * _BUFFER_SHARE, 2),
    )
    breakdown.total = round(
        breakdown.transport + breakdown.lodging + breakdown.food
        + breakdown.activities + breakdown.buffer, 2
    )
    return breakdown
