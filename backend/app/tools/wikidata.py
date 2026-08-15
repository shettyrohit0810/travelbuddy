"""Wikidata sitelink counts as a popularity signal.

The number of language editions that link to an entity is a free, verifiable proxy for
how significant a place is. It is what separates Kinkaku-ji (57 sitelinks) from a minor
neighbourhood temple (0-2) -- a distinction OpenStreetMap itself cannot express, since
OSM has no rating field at all.

This exists because the previous proxy was too coarse. Every Wikidata-linked feature
scored 4.0-4.5, so the scheduler's knapsack had nothing to separate them and ties broke
alphabetically: "Anyo Temple" was scheduled while Kinkaku-ji sat unselected in the same
candidate pool.

Design notes:
- **Batched.** Wikidata accepts up to 50 entity ids per request, so a 120-POI pool costs
  3 calls rather than 120.
- **Cached for a week.** Sitelink counts move on the order of months; re-fetching them
  per planning request would be pure waste against a donated public API.
- **Never fatal.** Any failure returns no counts, and callers fall back to the coarse
  proxy. A popularity signal is an improvement to ranking, not a correctness input --
  losing it must not change whether a plan is valid.
"""
import logging
import math
from typing import Dict, List, Optional

from app.core.cache import ttl_cache
from app.tools._http import get_json

logger = logging.getLogger("app.tools.wikidata")

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
BATCH_SIZE = 50
_HEADERS = {"User-Agent": "TravelBuddy/1.0 (github.com/shettyrohit0810/travelbuddy-trip-planner)"}

# Ratings must stay inside the 0-5 band the scheduler expects, so the raw count is
# compressed logarithmically rather than scaled linearly. Sitelink counts are extremely
# skewed -- a world landmark has 50-200 while a real but minor temple has 0-3 -- and a
# linear map would push everything except the top handful to the floor.
UNLINKED_SCORE = 3.0      # no Wikidata entity at all
LINKED_BASE_SCORE = 3.2   # has an entity, but few or no sitelinks
MAX_SCORE = 5.0


def score_from_sitelinks(count: Optional[int]) -> float:
    """Map a sitelink count onto the 0-5 band the knapsack maximises.

    0 sitelinks -> 3.2, ~10 -> ~4.0, ~60 -> ~4.8, capped at 5.0. `None` means "no
    Wikidata entity", which scores below even a zero-sitelink entity: having an entry at
    all is itself weak evidence someone considered the place noteworthy.
    """
    if count is None:
        return UNLINKED_SCORE
    if count <= 0:
        return LINKED_BASE_SCORE
    scaled = LINKED_BASE_SCORE + math.log10(1 + count) * 1.0
    return round(min(scaled, MAX_SCORE), 3)


@ttl_cache(seconds=604800, maxsize=64)  # one week
def _fetch_batch(qids_key: str) -> Dict[str, int]:
    """Fetch one batch. Takes a pipe-joined string so the result is cacheable."""
    # NOTE: no `maxlag`. It is a politeness throttle aimed at write traffic, and it
    # rejects read-only entity fetches whenever Wikidata's *query service* is lagged --
    # which it routinely is. An earlier version sent maxlag=5 and every lookup failed
    # with "Waiting for wdqs1014: 7.5 seconds lagged", silently disabling the whole
    # popularity signal.
    try:
        data = get_json(
            WIKIDATA_API,
            {"action": "wbgetentities", "ids": qids_key, "props": "sitelinks",
             "format": "json"},
            _HEADERS,
            timeout=20,
        )
    except Exception as e:
        logger.warning(f"Wikidata sitelink lookup failed for a batch of "
                       f"{len(qids_key.split('|'))}: {e}")
        return {}

    # The API reports rejections as HTTP 200 with an `error` object, so an unchecked
    # `.get("entities")` turns a real failure into an indistinguishable empty result --
    # exactly how the maxlag problem stayed invisible.
    if data.get("error"):
        err = data["error"]
        logger.warning(
            f"Wikidata rejected a sitelink batch: {err.get('code')} — {err.get('info')}"
        )
        return {}

    entities = data.get("entities") or {}
    counts: Dict[str, int] = {}
    for qid, entity in entities.items():
        if "missing" in entity:
            continue
        counts[qid] = len(entity.get("sitelinks") or {})
    return counts


def sitelink_counts(qids: List[str]) -> Dict[str, int]:
    """Sitelink count per Wikidata id. Missing ids are simply absent from the result.

    Returns partial results on partial failure rather than nothing: if two batches
    succeed and one fails, the POIs in the successful batches still get a real signal.
    """
    unique = sorted({q for q in qids if q and q.startswith("Q")})
    if not unique:
        return {}

    counts: Dict[str, int] = {}
    for start in range(0, len(unique), BATCH_SIZE):
        batch = unique[start:start + BATCH_SIZE]
        counts.update(_fetch_batch("|".join(batch)))
    return counts
