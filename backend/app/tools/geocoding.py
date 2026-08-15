"""Place-name resolution.

Uses OpenStreetMap's Nominatim, with Open-Meteo as a fallback. That ordering is the
whole point of this module rather than a preference.

Open-Meteo's dataset is a *populated-places* gazetteer: it has cities and towns, but no
administrative regions, and it ranks by population. Both properties produce silent, badly
wrong answers:

  - "Goa" → **Genoa, Italy** (pop 580k), because the Indian state is absent entirely and
    Genoa is the most populous fuzzy match. An entire itinerary of Italian churches,
    labelled as Goa.
  - "National Capital Region" → no match at all.

Nominatim resolves both correctly (Goa → the Indian state; regions are first-class), so
it leads. Open-Meteo remains as a fallback because Nominatim is a donated service with a
strict rate limit and does go down.

Whatever resolves, the caller is told *which place was chosen* -- when a name is
genuinely ambiguous, naming the winner is the only honest option.
"""
import logging
import math
from dataclasses import dataclass
from typing import Optional

from app.core.cache import ttl_cache
from app.tools._http import get_json

logger = logging.getLogger("app.tools.geocoding")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OPEN_METEO_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Nominatim's usage policy requires a real identifying User-Agent and caps callers at
# roughly one request per second. Results are cached for a week: place coordinates are
# effectively static, and re-querying per planning request would be abuse.
# Accept-Language matters for display, not correctness: without it Nominatim returns
# the endonym, so Kyoto comes back as "京都市, 京都府, 日本" in an English itinerary.
_HEADERS = {
    "User-Agent": "TravelBuddy/1.0 (+https://github.com/shettyrohit0810/travelbuddy)",
    "Accept-Language": "en",
}


# A search radius has to match the thing being searched. A city centroid with an 8km
# radius is right; a *state* centroid with the same radius is not -- Goa's attractions
# span ~100km, so an 8km circle around the geometric middle of the state found exactly
# one obscure archaeological site and the planner repeated it for three days.
MIN_RADIUS_M = 8_000
# Capped because Overpass cost grows with area, and past a point a "trip to X" spanning
# 60km of driving is not one trip anyway.
MAX_RADIUS_M = 45_000


@dataclass(frozen=True)
class ResolvedPlace:
    lat: float
    lon: float
    display_name: str
    kind: Optional[str] = None
    source: str = "nominatim"
    # (south, north, west, east) when the provider supplies it.
    bbox: Optional[tuple] = None

    @property
    def search_radius_m(self) -> int:
        """Radius covering the place's real extent, within sane bounds.

        Derived from the bounding box rather than the place *type* on purpose: type
        names vary by country and provider ("state", "region", "administrative"),
        while a bounding box means the same thing everywhere.
        """
        if not self.bbox:
            return MIN_RADIUS_M
        south, north, west, east = self.bbox
        lat_span_km = abs(north - south) * 111.0
        lon_span_km = abs(east - west) * 111.0 * max(math.cos(math.radians(self.lat)), 0.1)
        # Half the larger span reaches the far edge from the centroid.
        radius_m = int(max(lat_span_km, lon_span_km) / 2 * 1000)
        return max(MIN_RADIUS_M, min(radius_m, MAX_RADIUS_M))


@ttl_cache(seconds=604800, maxsize=256)
def resolve_location(name: str) -> Optional[ResolvedPlace]:
    place = _try_nominatim(name)
    if place is not None:
        return place
    logger.info("Nominatim gave nothing for %r; falling back to Open-Meteo.", name)
    return _try_open_meteo(name)


def _try_nominatim(name: str) -> Optional[ResolvedPlace]:
    try:
        results = get_json(
            NOMINATIM_URL,
            {"q": name, "format": "json", "limit": 3, "addressdetails": 1},
            _HEADERS, timeout=20,
        )
    except Exception as exc:
        logger.warning("Nominatim lookup failed for %r: %s", name, exc)
        return None

    if not results:
        return None

    top = results[0]
    bbox = None
    raw_bbox = top.get("boundingbox")
    if raw_bbox and len(raw_bbox) == 4:
        try:
            bbox = tuple(float(v) for v in raw_bbox)
        except (TypeError, ValueError):
            bbox = None

    return ResolvedPlace(
        lat=float(top["lat"]), lon=float(top["lon"]),
        display_name=_shorten(top.get("display_name", name)),
        kind=top.get("addresstype") or top.get("type"),
        source="nominatim", bbox=bbox,
    )


def _try_open_meteo(name: str) -> Optional[ResolvedPlace]:
    try:
        data = get_json(OPEN_METEO_URL, {"name": name, "count": 20}, timeout=15)
    except Exception as exc:
        logger.warning("Open-Meteo geocoding failed for %r: %s", name, exc)
        return None

    # Defensive: a provider returning an unexpected shape must degrade to "no match",
    # not raise. Geocoding failure is normal and already handled by every caller;
    # an AttributeError escaping from here would fail the whole planning request.
    if not isinstance(data, dict):
        logger.warning("Open-Meteo returned an unexpected payload for %r: %s",
                       name, type(data).__name__)
        return None

    results = data.get("results") or []
    if not results:
        return None

    # Prefer an exact name match over the API's population ranking -- that ranking is
    # exactly what turns "Goa" into Genoa.
    wanted = name.strip().lower()
    exact = [r for r in results if (r.get("name") or "").strip().lower() == wanted]
    chosen = max(exact, key=lambda r: r.get("population") or 0) if exact else results[0]

    display = ", ".join(filter(None, [chosen.get("name"), chosen.get("country")]))
    if not exact:
        logger.warning(
            "No exact match for %r; using nearest match %r. The plan will describe "
            "that place.", name, display,
        )
    return ResolvedPlace(
        lat=chosen["latitude"], lon=chosen["longitude"],
        display_name=display, kind=None, source="open-meteo",
    )


def _shorten(display_name: str, parts: int = 3) -> str:
    """Nominatim returns a full address chain; keep the leading, most specific parts."""
    segments = [s.strip() for s in display_name.split(",")]
    if len(segments) <= parts:
        return display_name
    return ", ".join(segments[:2] + [segments[-1]])
