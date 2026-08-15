from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class SaveTripRequest(BaseModel):
    destination: str
    days: int = Field(..., ge=1, le=30)
    travelers: int = Field(default=1, ge=1)
    plan_data: dict


class SavedTripOut(BaseModel):
    id: int
    destination: str
    days: int
    travelers: int
    plan_data: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class SavedTripList(BaseModel):
    trips: List[SavedTripOut]
    total: int
