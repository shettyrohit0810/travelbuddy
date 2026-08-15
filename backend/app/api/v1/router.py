from fastapi import APIRouter

from app.api.v1.endpoints import auth, planning, trips

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(planning.router, tags=["planning"])
api_router.include_router(trips.router, prefix="/trips", tags=["trips"])
