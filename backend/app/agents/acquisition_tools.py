"""Tools the acquisition agent may call.

Each returns a real observation from a real lookup -- nothing here is simulated, and
nothing returns a summary the agent has to take on trust. The agent sees counts and
names and decides what to do next.

These wrap the existing POI plumbing rather than replacing it. The agent can widen a
radius or change categories; it cannot change how a POI becomes a scheduler Candidate,
what a candidate costs, or which candidates get scheduled. That boundary is the whole
design: the agent chooses what to *retrieve*, deterministic code owns what to *do* with
it.
"""
import logging
from typing import Any, Dict, List, Optional

from app.tools._http import get_json
from app.tools import geocoding, poi_overpass

logger = logging.getLogger("app.agents.acquisition_tools")

MAX_RADIUS_METERS = 45000

# Agent turns run against a wall clock; a single lookup must not consume it.
AGENT_QUERY_TIMEOUT_S = 25
MAX_LIMIT = 200


def geocode_candidates(name: str, limit: int = 5) -> Dict[str, Any]:
    """Return ALL plausible resolutions, not just the top-ranked one.

    This is the tool that makes an ambiguous place name an agent's problem rather than
    a ranking rule's. The deterministic path has to commit to one match; an agent can
    look at "Genoa, Italy (pop 580k)" sitting above "Goa, India" for the query "Goa"
    and notice the mismatch. It never invents coordinates -- it only chooses among real
    candidates, each carrying the search radius implied by its own bounding box.
    """
    try:
        results = get_json(
            geocoding.NOMINATIM_URL,
            {"q": name, "format": "json", "limit": min(max(int(limit), 1), 10),
             "addressdetails": 1},
            geocoding._HEADERS, timeout=20,
        )
    except Exception as exc:
        logger.error(f"geocode_candidates failed for {name!r}: {exc}")
        return {"query": name, "error": str(exc), "candidates": []}

    candidates = []
    for item in results or []:
        bbox = None
        raw = item.get("boundingbox")
        if raw and len(raw) == 4:
            try:
                bbox = tuple(float(v) for v in raw)
            except (TypeError, ValueError):
                bbox = None
        try:
            place = geocoding.ResolvedPlace(
                lat=float(item["lat"]), lon=float(item["lon"]),
                display_name=geocoding._shorten(item.get("display_name", name)),
                kind=item.get("addresstype") or item.get("type"), bbox=bbox,
            )
        except (KeyError, TypeError, ValueError):
            continue
        candidates.append({
            "display_name": place.display_name,
            "kind": place.kind,
            "lat": place.lat,
            "lon": place.lon,
            # Surfaced so the agent can pass a radius matched to the place's real
            # extent rather than guessing one -- a city radius around a state centroid
            # is how a three-day plan ends up repeating one archaeological site.
            "suggested_radius_m": place.search_radius_m,
        })

    return {"query": name, "count": len(candidates), "candidates": candidates}


def search_pois(
    lat: float,
    lon: float,
    radius_m: int = poi_overpass.SEARCH_RADIUS_METERS,
    require_notable: bool = True,
    limit: int = 120,
) -> Dict[str, Any]:
    """Search POIs around explicit coordinates, with the two knobs that actually matter.

    `require_notable` toggles the Wikidata-link requirement. That requirement is what
    makes the default query both fast and landmark-heavy, but in a small town it can be
    the difference between 40 results and zero -- which is exactly the situation the
    agent exists to notice and respond to.
    """
    radius_m = max(500, min(int(radius_m), MAX_RADIUS_METERS))
    limit = max(1, min(int(limit), MAX_LIMIT))

    query = _build_query(lat, lon, radius_m, require_notable, limit)
    # One round, short timeout: an agent turn must leave room for the turns after
    # it. A dead provider should cost this call, not the whole investigation.
    data = poi_overpass._query_overpass(
        query, f"agent@{lat:.3f},{lon:.3f}", rounds=1, timeout_s=AGENT_QUERY_TIMEOUT_S
    )
    if data is None:
        return {"error": "provider unavailable", "count": 0, "pois": [], "radius_m": radius_m,
                "require_notable": require_notable}

    pois = poi_overpass.parse_elements(data.get("elements", []), limit)
    return {
        "count": len(pois),
        "radius_m": radius_m,
        "require_notable": require_notable,
        # Names only in the observation: enough for the agent to judge relevance without
        # flooding its context with coordinates it has no use for.
        "sample_names": [p["name"] for p in pois[:12]],
        "pois": pois,
    }


def _build_query(lat: float, lon: float, radius: int, require_notable: bool, limit: int) -> str:
    wikidata = '["wikidata"]' if require_notable else ""
    timeout = poi_overpass.OVERPASS_TIMEOUT_S
    return f"""[out:json][timeout:{timeout}];
(
  way["historic"]["name"]{wikidata}(around:{radius},{lat},{lon});
  way["amenity"="place_of_worship"]["name"]{wikidata}(around:{radius},{lat},{lon});
  way["tourism"]["name"]{wikidata}["tourism"!~"^(hotel|hostel|guest_house|motel|apartment|chalet|camp_site|caravan_site|information|picnic_site)$"](around:{radius},{lat},{lon});
  node["tourism"~"^(attraction|museum|viewpoint|gallery|theme_park|zoo|aquarium)$"]["name"]{wikidata}(around:{radius},{lat},{lon});
);
out center {limit};"""


TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "geocode_candidates",
        "description": (
            "List all plausible real-world locations matching a place name, with country, "
            "region and population. Use this when a destination name is ambiguous or when a "
            "search returned nothing, to check you are looking at the right place."
        ),
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["name"],
        },
    },
    {
        "name": "search_pois",
        "description": (
            "Search points of interest around coordinates. Increase radius_m to widen the "
            "search area. Set require_notable=false to include places without a Wikidata "
            "link -- this finds far more results in smaller towns, but they are less likely "
            "to be recognisable landmarks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "radius_m": {"type": "integer"},
                "require_notable": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
            "required": ["lat", "lon"],
        },
    },
]

TOOL_IMPLS = {
    "geocode_candidates": geocode_candidates,
    "search_pois": search_pois,
}
