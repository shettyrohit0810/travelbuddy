"""Planning endpoint.

Open to unauthenticated callers on purpose: planning reads no user-owned resource and
writes nothing. Saving a plan requires auth (see `trips.py`), which is where ownership
actually starts to matter.
"""
from fastapi import APIRouter

from app.agents.orchestrator import plan_trip
from app.schemas.trip import (
    TrajectoryOut, TripPlan, TripRequest, Verification, Violation,
)

router = APIRouter()


@router.post("/plan", response_model=TripPlan)
def create_plan(payload: TripRequest) -> TripPlan:
    state = plan_trip(query=payload.query, origin=payload.origin)

    verification = state.get("verification")
    verification_out = None
    if verification is not None:
        verification_out = Verification(
            valid=verification.valid,
            violations=[
                Violation(code=v.code, message=v.message,
                          repairable=v.repairable, overspend=v.overspend)
                for v in verification.violations
            ],
            repair_attempts=state.get("repair_attempts", 0),
        )

    return TripPlan(
        requirements=state.get("requirements"),
        weather=state.get("weather"),
        transport=state.get("transport") or [],
        budget=state.get("budget"),
        itinerary=state.get("itinerary"),
        verification=verification_out,
        trajectories=[TrajectoryOut(**t) for t in (state.get("trajectories") or [])],
        logs=state.get("logs") or [],
    )
