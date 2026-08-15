import logging
from app.core.config import settings
from app.core.cache import ttl_cache
from app.tools._http import get_json
from app.tools.poi_overpass import overpass_poi_search

logger = logging.getLogger("app.tools.destination_search")

BASE_URL = "https://api.opentripmap.com/0.1/en/places"
SEARCH_RADIUS_METERS = 12000
MAX_RESULTS = 20

# OpenTripMap's "rate" field is an importance tier (1-3, or 1h/2h/3h for the very top
# attractions), not a 0-5 rating. Map it onto something roughly comparable to the
# 0-5 scale the rest of the app expects, so callers can't mistake it for a % or star count.
_RATE_TO_SCORE = {"1": 2.5, "2": 3.5, "3": 4.5, "1h": 4.8, "2h": 4.9, "3h": 5.0}


@ttl_cache(seconds=1800)
def _geocode(location: str, api_key: str) -> tuple[float, float] | None:
    data = get_json(f"{BASE_URL}/geoname", {"name": location, "apikey": api_key})
    if data.get("status") == "error" or "lat" not in data:
        return None
    return data["lat"], data["lon"]


@ttl_cache(seconds=1800)
def destination_search(query: str, category: str = None) -> dict:
    """
    Real points-of-interest search via OpenTripMap (free tier, requires
    OPENTRIPMAP_API_KEY — see .env.example). Returns an empty activity list (not
    fake data) if the key is missing, the location can't be geocoded, or the call
    fails.
    """
    api_key = settings.OPENTRIPMAP_API_KEY
    if not api_key:
        # No key is the DEFAULT path, not a failure: Overpass needs no account, so a
        # fresh clone still produces really-grounded itineraries. OpenTripMap stays
        # supported for its richer importance ranking when a key is available.
        logger.info("OPENTRIPMAP_API_KEY not set; using keyless OpenStreetMap Overpass for POIs.")
        return overpass_poi_search(query)

    try:
        coords = _geocode(query, api_key)
        if coords is None:
            logger.warning(f"OpenTripMap geocoding found no match for destination: {query!r}")
            return {"destination": query, "results_count": 0, "activities": [], "source": "opentripmap"}

        lat, lon = coords
        params = {
            "radius": SEARCH_RADIUS_METERS,
            "lon": lon,
            "lat": lat,
            "format": "json",
            "limit": MAX_RESULTS,
            "apikey": api_key,
        }
        if category:
            params["kinds"] = category
        places = get_json(f"{BASE_URL}/radius", params)
    except Exception as e:
        logger.error(f"OpenTripMap search failed for {query!r}: {e}")
        return {"destination": query, "results_count": 0, "activities": [], "source": "opentripmap"}

    activities = []
    for place in places:
        name = place.get("name")
        point = place.get("point") or {}
        lat, lon = point.get("lat"), point.get("lon")
        # Skip places missing a name or coordinates rather than defaulting to a
        # fabricated (0, 0), which would silently corrupt the scheduler's
        # travel-time math with a point in the Gulf of Guinea.
        if not name or lat is None or lon is None:
            continue
        kinds = (place.get("kinds") or "").split(",")
        activities.append({
            "name": name,
            "category": kinds[0] if kinds and kinds[0] else "attraction",
            "rating": _RATE_TO_SCORE.get(str(place.get("rate")), 3.0),
            "lat": lat,
            "lon": lon,
        })

    return {
        "destination": query,
        "results_count": len(activities),
        "activities": activities,
        "source": "opentripmap",
    }
