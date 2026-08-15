from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Coordinates:
    lat: float
    lon: float


@dataclass(frozen=True)
class TimeWindow:
    start_min: int
    end_min: int


@dataclass(frozen=True)
class Candidate:
    name: str
    category: str
    rating: float
    coords: Coordinates
    source: str
    estimated_cost: float
    open_windows: Optional[List[TimeWindow]] = None
    mandatory: bool = False


@dataclass(frozen=True)
class ScheduleConstraints:
    days: int
    day_start_min: int = 540
    day_end_min: int = 1260
    visit_duration_min: int = 120
    start_location: Optional[Coordinates] = None
    activities_budget: Optional[float] = None
    max_slots_per_day: int = 3


@dataclass(frozen=True)
class ScheduledSlot:
    day: int
    slot_index: int
    start_min: int
    end_min: int
    name: str
    category: str
    source: str
    travel_min_from_previous: float
    estimated_cost: float


@dataclass(frozen=True)
class DaySchedule:
    day: int
    slots: List[ScheduledSlot]
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScheduleResult:
    days: List[DaySchedule]
    total_estimated_cost: float
    warnings: List[str] = field(default_factory=list)
