"""Saved trips.

Every route derives the owner from the bearer token and filters on it. No endpoint
accepts a `user_id` argument -- a client-supplied identifier is an assertion, not proof,
and trusting one is an IDOR by construction.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.trip import Trip
from app.models.user import User
from app.schemas.saved_trip import SavedTripList, SavedTripOut, SaveTripRequest

router = APIRouter()


def _owned(trip_id: int, user: User, db: Session) -> Trip:
    trip = db.query(Trip).filter(Trip.id == trip_id, Trip.user_id == user.id).first()
    if trip is None:
        # 404 rather than 403: a 403 would confirm the id exists for somebody else.
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.post("", response_model=SavedTripOut, status_code=status.HTTP_201_CREATED)
def save_trip(payload: SaveTripRequest, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    trip = Trip(
        user_id=user.id, destination=payload.destination, days=payload.days,
        travelers=payload.travelers, plan_data=payload.plan_data,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


@router.get("", response_model=SavedTripList)
def list_trips(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Trip).filter(Trip.user_id == user.id).order_by(Trip.created_at.desc())
    trips = query.all()
    return SavedTripList(trips=trips, total=len(trips))


@router.get("/{trip_id}", response_model=SavedTripOut)
def get_trip(trip_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    return _owned(trip_id, user, db)


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trip(trip_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    db.delete(_owned(trip_id, user, db))
    db.commit()
