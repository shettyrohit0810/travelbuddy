import math

from app.scheduling.models import Coordinates

EARTH_RADIUS_KM = 6371.0


def haversine_km(a: Coordinates, b: Coordinates) -> float:
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


class HaversineTravelTimeProvider:
    """TravelTimeProvider backed by real coordinates + an assumed average speed.
    Not a real routing API (no roads/traffic), but grounded in real distance, not
    guessed. See the design spec's "Travel time" decision for the tradeoff."""

    def __init__(self, speed_kmh: float = 20.0):
        self.speed_kmh = speed_kmh

    def minutes_between(self, a: Coordinates, b: Coordinates) -> float:
        distance_km = haversine_km(a, b)
        hours = distance_km / self.speed_kmh
        return hours * 60.0
