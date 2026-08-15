from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Trip(Base):
    """A saved plan.

    `plan_data` is JSONB rather than normalised tables on purpose: the plan shape is
    owned by the planner and changes with it, and nothing queries *into* a plan -- trips
    are always read whole. Normalising it would buy joins nobody performs at the cost of
    a migration every time a planner field moves.
    """
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    destination: Mapped[str] = mapped_column(String(200))
    days: Mapped[int] = mapped_column(Integer)
    travelers: Mapped[int] = mapped_column(Integer, default=1)
    plan_data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    user = relationship("User", back_populates="trips")
