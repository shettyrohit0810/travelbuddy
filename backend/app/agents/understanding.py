"""Turn a free-text request into structured requirements.

Rule-based by default, with an optional LLM path. The rules are not a fallback of last
resort -- they are the path that runs in every unconfigured deployment, so the budget
regex in particular is load-bearing: if it misses, `budget` is None, and the entire
hard-budget constraint downstream becomes silently inert.
"""
import logging
import re
from typing import Optional

from app.core.config import settings
from app.schemas.trip import TripRequirements

logger = logging.getLogger("app.agents.understanding")

# Matches "budget of 16000", "budget 25,000", "under 5000", "₹12000", "rs. 8000".
# The optional filler between keyword and number is the part that keeps breaking when
# someone simplifies this: "a budget of X" is the single most common phrasing.
_BUDGET = re.compile(
    r"(?:under|budget|rs\.?|inr|₹|\$)\s*(?:of\s+)?(?:rs\.?|inr|₹|\$)?\s*([\d,]+)", re.I
)
_DAYS = re.compile(r"(\d+)\s*[- ]?\s*day", re.I)
_PEOPLE = re.compile(r"(\d+)\s*(?:people|persons?|travell?ers?|adults?|friends)", re.I)
_DESTINATION = re.compile(
    r"\b(?:to|in|visit|visiting)\s+([A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*){0,3})"
)

_INTERESTS = {
    "beach": ["beach", "coastal", "seaside"],
    "culture": ["culture", "cultural", "heritage", "temple", "museum", "historic"],
    "food": ["food", "cuisine", "culinary", "street food", "dining"],
    "nature": ["nature", "hiking", "trek", "mountain", "wildlife", "park"],
    "nightlife": ["nightlife", "clubs", "bars", "party"],
    "shopping": ["shopping", "markets", "bazaar"],
    "art": ["art", "gallery", "street-art", "street art"],
}


def _extract_interests(text: str) -> list[str]:
    lowered = text.lower()
    return [name for name, words in _INTERESTS.items() if any(w in lowered for w in words)]


def parse_request(query: str) -> TripRequirements:
    budget: Optional[float] = None
    match = _BUDGET.search(query)
    if match:
        budget = float(match.group(1).replace(",", ""))

    days = int(_DAYS.search(query).group(1)) if _DAYS.search(query) else None
    travelers = int(_PEOPLE.search(query).group(1)) if _PEOPLE.search(query) else None

    destination = None
    dest_match = _DESTINATION.search(query)
    if dest_match:
        # Trim trailing filler the greedy capital-word run can swallow, e.g.
        # "to Kyoto With A" from "trip to Kyoto with a budget of ...".
        candidate = dest_match.group(1).strip()
        stop_words = {"With", "For", "And", "On", "At", "Under", "A", "The"}
        parts = [p for p in candidate.split() if p not in stop_words]
        destination = " ".join(parts) or None

    return TripRequirements(
        destination=destination,
        days=days,
        travelers=travelers,
        budget=budget,
        interests=_extract_interests(query),
    )
