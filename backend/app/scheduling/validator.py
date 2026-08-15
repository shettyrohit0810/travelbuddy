from dataclasses import dataclass, field
from typing import List

from app.scheduling.models import ScheduleConstraints, ScheduleResult


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    violations: List[str] = field(default_factory=list)


def validate(result: ScheduleResult, constraints: ScheduleConstraints) -> ValidationResult:
    """
    Independently re-checks a ScheduleResult against ScheduleConstraints -- a
    trust-but-verify safety net over build_schedule's own logic, and the reusable
    seed for Phase 4's hard-constraint plan verifier.
    """
    violations: List[str] = []

    for day_schedule in result.days:
        prev_end = None
        for slot in day_schedule.slots:
            if slot.start_min < constraints.day_start_min:
                violations.append(
                    f"Day {day_schedule.day}: slot '{slot.name}' starts before day_start_min"
                )
            if slot.end_min > constraints.day_end_min:
                violations.append(
                    f"Day {day_schedule.day}: slot '{slot.name}' ends after day_end_min"
                )
            if prev_end is not None and slot.start_min < prev_end:
                violations.append(
                    f"Day {day_schedule.day}: slot '{slot.name}' overlaps the previous slot"
                )
            prev_end = slot.end_min

    if constraints.activities_budget is not None and result.total_estimated_cost > constraints.activities_budget + 1e-6:
        violations.append(
            f"Total estimated cost {result.total_estimated_cost} exceeds activities_budget {constraints.activities_budget}"
        )

    return ValidationResult(valid=not violations, violations=violations)
