from typing import Protocol, runtime_checkable

from app.scheduling.models import Coordinates


@runtime_checkable
class TravelTimeProvider(Protocol):
    def minutes_between(self, a: Coordinates, b: Coordinates) -> float:
        ...


@runtime_checkable
class CostEstimator(Protocol):
    def estimate(self, category: str) -> float:
        ...
