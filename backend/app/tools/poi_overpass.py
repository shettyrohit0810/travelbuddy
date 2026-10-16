"""Points of interest from OpenStreetMap via the Overpass API.

Chosen as the default POI source because it needs **no API key and no account**, so a
fresh clone of this repo produces real, grounded itineraries out of the box rather than
the empty-results path. OpenTripMap remains supported when a key is configured (see
`destination_search`), but nothing depends on one existing.

Two honest limitations drive the design here, and both are worth reading before
trusting any number this module produces:

1. **OSM has no ratings.** There is no user-rating field to map onto the 0-5 scale the
   scheduler's knapsack maximises. Rather than invent one, `_notability_score` derives a
   coarse proxy from whether a feature is linked to Wikidata/Wikipedia -- a reasonable
   stand-in for "is this a landmark or a bus shelter", but explicitly NOT a quality
   rating, and it should never be presented to a user as one.

2. **Cost data is usually missing.** The `fee` tag is absent on most features. Treating
   absent-as-free would let unpriced attractions be selected as zero-cost against a
   tight budget -- exactly the class of bug the Hypothesis property test already caught
   once in the knapsack. So absence is treated as "probably costs something" and falls
   back to the category rate estimate. Only an explicit `fee=no` yields 0.0.
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.cache import ttl_cache
from app.tools._http import get_json, post_form
from app.scheduling.costs import StaticCostEstimator
from app.tools.wikidata import sitelink_counts, score_from_sitelinks

logger = logging.getLogger("app.tools.poi_overpass")

# Primary plus a mirror. Overpass is a shared community service that returns 429s and
# empty results under load -- observed during development, where an identical query
# returned 0 elements once and 300 moments later. A single transient failure should not
# silently degrade a trip to "no attractions found".
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

SEARCH_RADIUS_METERS = 8000
MAX_RESULTS = 120
OVERPASS_TIMEOUT_S = 90

# Overpass asks clients to identify themselves so abusive traffic can be blocked
# without banning the whole shared endpoint.
_HEADERS = {"User-Agent": "TravelBuddy/1.0 (github.com/shettyrohit0810/travelbuddy-trip-planner)"}

# OSM tag -> the category keys ACTIVITY_COST_BY_CATEGORY already understands, so cost
# estimation stays consistent with the rest of the planner.
_TOURISM_CATEGORY = {
    "museum": "museums",
    "gallery": "museums",
    "artwork": "cultural",
    "attraction": "cultural",
    "viewpoint": "view_points",
    "theme_park": "amusements",
    "zoo": "amusements",
    "aquarium": "amusements",
}
_LEISURE_CATEGORY = {"park": "natural", "garden": "natural", "nature_reserve": "natural"}


def _category_for(tags: Dict[str, str]) -> str:
    tourism = tags.get("tourism")
    if tourism in _TOURISM_CATEGORY:
        return _TOURISM_CATEGORY[tourism]
    leisure = tags.get("leisure")
    if leisure in _LEISURE_CATEGORY:
        return _LEISURE_CATEGORY[leisure]
    if tags.get("historic"):
        return "historic"
    if tags.get("amenity") == "place_of_worship":
        return "religion"
    return "cultural"


def _notability_score(tags: Dict[str, str]) -> float:
    """A coarse prominence proxy, NOT a user rating -- OSM has no ratings.

    Features that editors bothered to cross-link to Wikidata/Wikipedia are
    overwhelmingly the ones a traveller would recognise; unlinked ones skew toward
    minor markers, plaques and trail junctions. Scores stay inside the 0-5 band the
    scheduler expects so the knapsack keeps working unchanged.
    """
    has_wikidata = bool(tags.get("wikidata"))
    has_wikipedia = bool(tags.get("wikipedia"))
    if has_wikidata and has_wikipedia:
        return 4.5
    if has_wikidata or has_wikipedia:
        return 4.0
    if tags.get("tourism") in ("museum", "gallery", "theme_park", "zoo", "aquarium"):
        return 3.5
    return 3.0


def _cost_for(tags: Dict[str, str], category: str, estimator: StaticCostEstimator) -> float:
    """Cost policy. Absence of a fee tag must never mean 'free' -- see module docstring.

    The `charge` tag is deliberately IGNORED even when present: its values carry mixed
    and often unparseable currencies ("500 JPY", "5 EUR", "£3.50"), and converting
    them would require an FX source this project does not have. Silently mixing
    currencies into a single budget total would be a correctness bug that the verifier
    could not catch, so a labelled per-category estimate is the honest choice.
    """
    if tags.get("fee") == "no":
        return 0.0
    return estimator.estimate(category)


def _coords_of(element: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Nodes carry lat/lon directly; ways and relations only via `out center`."""
    if element.get("lat") is not None and element.get("lon") is not None:
        return element["lat"], element["lon"]
    center = element.get("center") or {}
    if center.get("lat") is not None and center.get("lon") is not None:
        return center["lat"], center["lon"]
    return None


def _geocode(location: str):
    """Delegates to the shared geocoder so POI lookup and the rest of the planner can
    never disagree about which "Goa" a trip is about. Returns the search radius too:
    it is a property of the resolved place, not a constant."""
    from app.tools.geocoding import resolve_location as _resolve
    place = _resolve(location)
    if place is None:
        return None
    return place.lat, place.lon, place.display_name, place.search_radius_m


def resolve_location(name: str):
    """Re-exported for the orchestrator's geocode node."""
    from app.tools.geocoding import resolve_location as _resolve
    return _resolve(name)


def _build_query(lat: float, lon: float, radius: int = SEARCH_RADIUS_METERS) -> str:
    """Two independently-capped result sets, which is the whole trick.

    A single `out center N` truncates the union arbitrarily (Overpass emits nodes
    before ways, and a city like Kyoto has thousands of minor `historic` nodes). That
    crowded every famous landmark out of the results: an early version of this query
    returned six obscure municipal museums for Kyoto and not one of Kinkaku-ji,
    Fushimi Inari, Kiyomizu-dera or Nijō Castle -- all of which are ways, and all of
    which sat below the cut.

    The `tourism` key filter excludes accommodation values explicitly. A key-only
    `["tourism"]` match also catches `tourism=hotel`, which put "ANA Crowne Plaza Kyoto"
    and "Mitsui Garden Hotel" into a sightseeing list on the first working run.

    Requiring a `wikidata` link is what makes this both fast and good. It is the
    difference between scanning every tagged feature in a dense city and scanning only
    the ones editors cross-referenced to an encyclopedia entry -- which is almost
    exactly the set a traveller would recognise. `out center` gives areas (most large
    sites are ways, not points) a usable coordinate.

`node`/`way` are named explicitly rather than using the `nwr` shorthand, and there
    is no unfiltered fill pass. Three earlier versions timed out server-side: one swept
    every `historic` feature in the radius, one used `nwr` (which drags relations into
    an already-expensive tag scan), and one added an unfiltered tourism pass. Overpass
    signals these as **HTTP 200 with a `remark` field**, not an error status, so a
    too-expensive query is easy to misread as "this city has no attractions".

    Even so this is not fast: measured at roughly 60-85s cold for Kyoto. That is why
    results are cached for 24h per location -- the cost is paid once per city, and
    steady-state lookups are effectively free.
    """
    return f"""[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  way["historic"]["name"]["wikidata"](around:{radius},{lat},{lon});
  way["amenity"="place_of_worship"]["name"]["wikidata"](around:{radius},{lat},{lon});
  way["tourism"]["name"]["wikidata"]["tourism"!~"^(hotel|hostel|guest_house|motel|apartment|chalet|camp_site|caravan_site|information|picnic_site)$"](around:{radius},{lat},{lon});
  node["tourism"~"^(attraction|museum|viewpoint)$"]["name"]["wikidata"](around:{radius},{lat},{lon});
);
out center {MAX_RESULTS * 4};"""


OVERPASS_ROUNDS = 2
OVERPASS_BACKOFF_S = 5


def _query_overpass(query: str, location: str, rounds: Optional[int] = None,
                    timeout_s: Optional[int] = None) -> Optional[dict]:
    """Try every endpoint, then retry the whole set after a short backoff.

    Measured behaviour of the public Overpass instances under repeated use: the same
    query returned 300 elements, then a server-side timeout `remark`, then a 504, then
    300 elements again -- with no change to the query. A single attempt therefore says
    very little, so this makes two full passes before concluding a location genuinely
    has no data. Returns None only if everything fails.
    """
    # Callers on a clock (the acquisition agent) pass a tighter budget: the default
    # 2 rounds x 2 endpoints x 150s can exceed an entire agent wall-clock budget in
    # a single call, which is how one lookup consumed 118s of a 120s run.
    rounds = rounds or OVERPASS_ROUNDS
    request_timeout = timeout_s or (OVERPASS_TIMEOUT_S + 60)

    last_error = None
    for round_index in range(rounds):
        if round_index:
            time.sleep(OVERPASS_BACKOFF_S)
        for url in OVERPASS_ENDPOINTS:
            try:
                data = post_form(url, {"data": query}, headers=_HEADERS, timeout=request_timeout)
                if data.get("elements"):
                    return data
                # Overpass reports server-side query timeouts as HTTP 200 with an
                # empty element list and a `remark`, NOT as an error status. Surfacing
                # it is the difference between "this city has no attractions" and "my
                # query was too expensive" -- which look identical otherwise.
                last_error = data.get("remark") or "empty element list"
            except Exception as e:
                last_error = e
            logger.warning(
                f"Overpass {url} unusable for {location!r} "
                f"(round {round_index + 1}/{rounds}): {last_error}"
            )
    logger.error(f"All Overpass endpoints failed for {location!r}: {last_error}")
    return None


def _apply_popularity(activities: List[dict]) -> None:
    """Replace the coarse tag-based proxy with real Wikidata sitelink counts, in place.

    Falls back silently per-POI: an activity with no Wikidata id, or one Wikidata could
    not resolve, keeps the tag-based score. That matters -- a partial API response must
    not reorder the whole pool by pushing unresolved entries to the floor.
    """
    qids = [a.get("wikidata") for a in activities if a.get("wikidata")]
    if not qids:
        return

    counts = sitelink_counts(qids)
    if not counts:
        logger.info("No Wikidata sitelink data available; keeping tag-based ranking.")
        return

    enriched = 0
    for activity in activities:
        qid = activity.get("wikidata")
        if qid and qid in counts:
            activity["sitelinks"] = counts[qid]
            activity["rating"] = score_from_sitelinks(counts[qid])
            enriched += 1
    logger.info(f"Popularity signal applied to {enriched}/{len(activities)} POIs.")


def parse_elements(elements: list, limit: int) -> List[dict]:
    """Turn raw Overpass elements into activity dicts.

    Extracted so the acquisition agent's tools produce byte-identical output to the
    default path -- if the agent's widened search returned differently-shaped data, the
    scheduler would be consuming two different contracts depending on whether an agent
    happened to run.
    """
    estimator = StaticCostEstimator()
    activities: List[dict] = []
    seen_names = set()

    for element in elements:
        tags = element.get("tags") or {}
        # Prefer an English name when the mapper supplied one; fall back to the local
        # name rather than dropping the feature.
        name = tags.get("name:en") or tags.get("name")
        if not name:
            continue

        key = name.strip().lower()
        # Overpass commonly returns the same place as both a node and a way.
        if key in seen_names:
            continue

        point = _coords_of(element)
        if point is None:
            continue

        category = _category_for(tags)
        seen_names.add(key)
        activities.append({
            "name": name,
            "category": category,
            "rating": _notability_score(tags),
            "lat": point[0],
            "lon": point[1],
            "estimated_cost": _cost_for(tags, category, estimator),
            "cost_is_estimate": tags.get("fee") != "no",
            "wikidata": tags.get("wikidata"),
        })

    _apply_popularity(activities)

    # Most prominent first. NOTE the cap is deliberately generous: every Wikidata-linked
    # feature scores 4.0-4.5, so ties break alphabetically, and a tight cap truncates the
    # pool at roughly the letter E -- which is how Nijō Castle lost its place to "Anyo
    # Temple" on an earlier run. A large pool lets the knapsack decide on cost and travel
    # time (which is the point of having a scheduler) instead of the alphabet deciding.
    activities.sort(key=lambda a: (-a["rating"], a["name"]))
    return activities[:limit]


@ttl_cache(seconds=86400)
def overpass_poi_search(location: str) -> dict:
    """Real POIs for a location. Returns an empty activity list -- never fabricated
    data -- if geocoding fails, Overpass errors, or nothing usable comes back.

    Cached for 24h per location: Overpass is a shared community endpoint with real
    rate limits, and repeated eval runs would otherwise hammer it.
    """
    # Escape hatch for CI and offline runs. Overpass is a free community service and
    # hitting it on every push is both slow (60-100s per unseen city) and impolite.
    # Set to any non-empty value to take the honest-degradation path instead.
    if os.environ.get("TRAVELBUDDY_DISABLE_LIVE_POI"):
        logger.info("TRAVELBUDDY_DISABLE_LIVE_POI set; skipping live Overpass lookup.")
        return {"destination": location, "results_count": 0, "activities": [],
                "source": "disabled", "resolved_location": None}

    geo = _geocode(location)
    if geo is None:
        return {"destination": location, "results_count": 0, "activities": [],
                "source": "overpass", "resolved_location": None}

    lat, lon, resolved, radius = geo
    logger.info("Searching POIs within %.0fkm of %s.", radius / 1000, resolved)
    data = _query_overpass(_build_query(lat, lon, radius), location)
    if data is None:
        # Covers HTTP 429 (rate limited) and 504 (query timeout), both of which Overpass
        # returns under load. Degrade to no results rather than inventing places.
        return {"destination": location, "results_count": 0, "activities": [], "source": "overpass", "resolved_location": resolved}

    activities = parse_elements(data.get("elements", []), MAX_RESULTS)
    if not activities:
        logger.warning(f"Overpass returned no usable POIs for {location!r}")

    return {
        "destination": location,
        # What was ACTUALLY planned. Surfaced so a mismatch between the request and the
        # resolved place is visible instead of silently baked into the itinerary.
        "resolved_location": resolved,
        "results_count": len(activities),
        "activities": activities,
        "source": "overpass",
    }
