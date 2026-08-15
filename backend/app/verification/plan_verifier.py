"""Hard-constraint verification for an assembled plan.

Deliberately arithmetic, never a model reviewing its own work. The graph routes on
these results, so a violation has to be a fact rather than an opinion -- "does this look
right?" asked of an LLM is not something you can build control flow on.

Checks: the traveller's budget ceiling, trip length, per-day slot ordering, and whether
every scheduled fact carries a source. That last one is what makes "nothing is invented"
enforceable rather than aspirational.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from app.schemas.trip import BudgetBreakdown, Itinerary, TripRequirements

BUDGET_OVERRUN = "budget_overrun"
ACTIVITIES_OVERSPEND = "activities_overspend"
DAY_COUNT_MISMATCH = "day_count_mismatch"
STOP_OVERLAP = "stop_overlap"
UNGROUNDED_FACT = "ungrounded_fact"

_TOLERANCE = 0.01  # currency rounding noise, not a real overrun


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    repairable: bool
    overspend: Optional[float] = None


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    violations: List[Violation] = field(default_factory=list)

    @property
    def repairable(self) -> List[Violation]:
        return [v for v in self.violations if v.repairable]


def _minutes(hhmm: str) -> Optional[int]:
    try:
        hours, minutes = hhmm.split(":")
        return int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return None


def verify_plan(
    requirements: Optional[TripRequirements],
    budget: Optional[BudgetBreakdown],
    itinerary: Optional[Itinerary],
) -> VerificationResult:
    """Return every violation found rather than short-circuiting, so the repair step
    sees the whole picture before deciding what to change."""
    violations: List[Violation] = []

    ceiling = requirements.budget if requirements else None
    if ceiling is not None and budget is not None and budget.total > ceiling + _TOLERANCE:
        overspend = round(budget.total - ceiling, 2)
        violations.append(Violation(
            BUDGET_OVERRUN,
            f"Plan total {budget.total} exceeds the stated budget {ceiling} by {overspend}",
            repairable=True, overspend=overspend,
        ))

    if itinerary is None:
        return VerificationResult(valid=not violations, violations=violations)

    requested_days = requirements.days if requirements else None
    if requested_days is not None and len(itinerary.days) != requested_days:
        violations.append(Violation(
            DAY_COUNT_MISMATCH,
            f"Itinerary covers {len(itinerary.days)} day(s) but {requested_days} were requested",
            # The scheduler guarantees one day per requested day, so this firing means
            # something upstream is broken -- retrying the same pipeline won't fix it.
            repairable=False,
        ))

    activities_spend = 0.0
    for day in itinerary.days:
        previous_end = None
        for stop in day.stops:
            activities_spend += stop.estimated_cost

            if not stop.source or not stop.source.strip():
                violations.append(Violation(
                    UNGROUNDED_FACT,
                    f"Day {day.day}: '{stop.name}' has no source attribution",
                    repairable=False,
                ))

            start, end = _minutes(stop.start_time), _minutes(stop.end_time)
            if start is None or end is None:
                continue
            if previous_end is not None and start < previous_end:
                violations.append(Violation(
                    STOP_OVERLAP,
                    f"Day {day.day}: '{stop.name}' starts before the previous stop ends",
                    repairable=False,
                ))
            previous_end = end

    if budget is not None and activities_spend > budget.activities + _TOLERANCE:
        overspend = round(activities_spend - budget.activities, 2)
        violations.append(Violation(
            ACTIVITIES_OVERSPEND,
            f"Scheduled activities cost {round(activities_spend, 2)} exceeds the "
            f"allocated {budget.activities} by {overspend}",
            repairable=True, overspend=overspend,
        ))

    return VerificationResult(valid=not violations, violations=violations)
