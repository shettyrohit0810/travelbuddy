"""Transport cost estimation.

A labelled distance-band estimate, not a live fare lookup. This is stated in the source
and surfaced as `source="estimate"` because the number flows into the budget the
verifier treats as ground truth -- and a fabricated fare presented as real pricing would
make an unsatisfiable trip look satisfiable.
"""
from typing import List

from app.schemas.trip import TransportOption
from app.scheduling.geo import haversine_km

# Rough INR-per-km bands. Deliberately coarse: precision here would imply a fare model
# this project does not have.
_BANDS = [
    (300, "Road transfer", 6.0, "under 5h by road"),
    (1200, "Train", 2.5, "overnight rail"),
    (float("inf"), "Flight", 5.5, "2-4h flight"),
]
_MIN_FARE = 800.0


def estimate_transport(origin_coords, destination_coords, travelers: int = 1) -> List[TransportOption]:
    if not origin_coords or not destination_coords:
        return []

    distance_km = haversine_km(origin_coords, destination_coords)
    options: List[TransportOption] = []
    for max_km, mode, rate, duration in _BANDS:
        if distance_km <= max_km:
            per_person = max(distance_km * rate, _MIN_FARE)
            options.append(TransportOption(
                mode=mode,
                estimated_cost=round(per_person * max(travelers, 1), 2),
                duration=duration,
                source="estimate",
            ))
            break
    return options
