"""Request/response shapes for planning.

`ScheduledStop` carries `source` deliberately. The verifier rejects any scheduled fact
without attribution, so the field is part of the correctness contract rather than
decoration -- it is what makes "every stop traces to a real lookup" checkable instead
of merely intended.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class TripRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)
    origin: str = Field(default="Mumbai")


class TripRequirements(BaseModel):
    destination: Optional[str] = None
    days: Optional[int] = Field(default=None, ge=1, le=30)
    travelers: Optional[int] = Field(default=None, ge=1)
    budget: Optional[float] = Field(default=None, ge=0)
    interests: List[str] = Field(default_factory=list)


class WeatherOutlook(BaseModel):
    summary: str
    avg_high_c: Optional[float] = None
    rain_chance_pct: Optional[float] = None
    suitability: int = Field(default=50, ge=0, le=100)
    warnings: List[str] = Field(default_factory=list)
    source: str


class TransportOption(BaseModel):
    mode: str
    estimated_cost: float
    duration: Optional[str] = None
    source: str


class BudgetBreakdown(BaseModel):
    transport: float = 0.0
    lodging: float = 0.0
    food: float = 0.0
    activities: float = 0.0
    buffer: float = 0.0
    total: float = 0.0


class ScheduledStop(BaseModel):
    name: str
    category: str
    start_time: str
    end_time: str
    travel_minutes_from_previous: float
    estimated_cost: float
    source: str = Field(..., description="Which lookup produced this; unattributed stops fail verification")


class DayPlan(BaseModel):
    day: int
    narrative: str
    stops: List[ScheduledStop] = Field(default_factory=list)


class Itinerary(BaseModel):
    destination: str
    resolved_location: Optional[str] = None
    days: List[DayPlan] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class Violation(BaseModel):
    code: str
    message: str
    repairable: bool
    overspend: Optional[float] = None


class Verification(BaseModel):
    valid: bool
    violations: List[Violation] = Field(default_factory=list)
    repair_attempts: int = 0


class TrajectoryStepOut(BaseModel):
    index: int
    kind: str
    name: str
    arguments: Optional[dict] = None
    observation: Optional[object] = None
    reasoning: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None


class TrajectoryOut(BaseModel):
    agent: str
    goal: str
    steps: List[TrajectoryStepOut] = Field(default_factory=list)
    outcome: Optional[str] = None
    summary: Optional[str] = None
    tool_calls_used: int = 0
    tool_call_budget: Optional[int] = None
    wall_clock_ms: Optional[float] = None


class TripPlan(BaseModel):
    requirements: Optional[TripRequirements] = None
    weather: Optional[WeatherOutlook] = None
    transport: List[TransportOption] = Field(default_factory=list)
    budget: Optional[BudgetBreakdown] = None
    itinerary: Optional[Itinerary] = None
    verification: Optional[Verification] = None
    trajectories: List[TrajectoryOut] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
