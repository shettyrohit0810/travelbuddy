"""Popularity signal: scoring curve, batching, and graceful degradation.

The degradation tests matter most. Ranking quality is an improvement; correctness is
owned by the verifier. A Wikidata outage must never change whether a plan is valid, and
must never silently reorder the pool by pushing unresolved POIs to the floor.
"""
from unittest.mock import patch

import pytest

from app.tools.wikidata import (
    score_from_sitelinks, sitelink_counts, _fetch_batch,
    UNLINKED_SCORE, LINKED_BASE_SCORE, MAX_SCORE, BATCH_SIZE,
)


def test_score_separates_a_landmark_from_a_minor_site():
    """The whole point: Kinkaku-ji (57) must outrank a 1-sitelink neighbourhood temple."""
    assert score_from_sitelinks(57) > score_from_sitelinks(1)
    assert score_from_sitelinks(1) > score_from_sitelinks(0)


def test_score_stays_inside_the_band_the_knapsack_expects():
    for count in [None, 0, 1, 10, 57, 500, 100000]:
        assert 0.0 <= score_from_sitelinks(count) <= MAX_SCORE


def test_no_wikidata_entity_scores_below_a_zero_sitelink_entity():
    """Having an entry at all is weak evidence someone thought the place noteworthy."""
    assert score_from_sitelinks(None) == UNLINKED_SCORE
    assert score_from_sitelinks(0) == LINKED_BASE_SCORE
    assert UNLINKED_SCORE < LINKED_BASE_SCORE


def test_score_is_compressed_not_linear():
    """Counts are heavily skewed; a linear map would floor everything but the top few."""
    low = score_from_sitelinks(5)
    mid = score_from_sitelinks(50)
    high = score_from_sitelinks(500)
    assert (mid - low) > (high - mid)


@patch("app.tools.wikidata.get_json")
def test_sitelink_counts_batches_requests(mock_get):
    mock_get.return_value = {"entities": {}}
    _fetch_batch.cache_clear()
    sitelink_counts([f"Q{i}" for i in range(BATCH_SIZE * 2 + 5)])
    assert mock_get.call_count == 3


@patch("app.tools.wikidata.get_json")
def test_missing_entities_are_skipped_not_counted_as_zero(mock_get):
    mock_get.return_value = {"entities": {
        "Q1": {"sitelinks": {"en": {}, "fr": {}}},
        "Q2": {"missing": ""},
    }}
    _fetch_batch.cache_clear()
    result = sitelink_counts(["Q1", "Q2"])
    assert result == {"Q1": 2}


@patch("app.tools.wikidata.get_json", side_effect=Exception("wikidata down"))
def test_api_failure_yields_no_counts_rather_than_raising(mock_get):
    _fetch_batch.cache_clear()
    assert sitelink_counts(["Q1", "Q2"]) == {}


def test_non_qid_inputs_are_ignored():
    assert sitelink_counts([None, "", "not-a-qid"]) == {}


# --- integration with the POI parser ------------------------------------------

ELEMENTS = [
    {"lat": 35.0, "lon": 135.0, "tags": {"name": "Famous Temple", "historic": "yes", "wikidata": "Q1"}},
    {"lat": 35.1, "lon": 135.1, "tags": {"name": "Minor Shrine", "historic": "yes", "wikidata": "Q2"}},
    {"lat": 35.2, "lon": 135.2, "tags": {"name": "Unlinked Place", "historic": "yes"}},
]


@patch("app.tools.poi_overpass.sitelink_counts", return_value={"Q1": 57, "Q2": 1})
def test_parser_ranks_by_real_popularity(mock_counts):
    from app.tools.poi_overpass import parse_elements
    activities = parse_elements(ELEMENTS, 10)
    assert [a["name"] for a in activities][0] == "Famous Temple"
    famous = next(a for a in activities if a["name"] == "Famous Temple")
    assert famous["sitelinks"] == 57


@patch("app.tools.poi_overpass.sitelink_counts", return_value={})
def test_parser_keeps_tag_based_ranking_when_wikidata_is_unavailable(mock_counts):
    """A total outage must leave the pool intact, not collapse every score."""
    from app.tools.poi_overpass import parse_elements
    activities = parse_elements(ELEMENTS, 10)
    assert len(activities) == 3
    assert all(a["rating"] > 0 for a in activities)
    assert all("sitelinks" not in a for a in activities)


@patch("app.tools.poi_overpass.sitelink_counts", return_value={"Q1": 57})
def test_partial_wikidata_response_does_not_floor_unresolved_pois(mock_counts):
    from app.tools.poi_overpass import parse_elements
    activities = parse_elements(ELEMENTS, 10)
    minor = next(a for a in activities if a["name"] == "Minor Shrine")
    # Q2 was not returned -- it must keep its tag-based score, not drop to a floor.
    assert minor["rating"] >= 4.0
    assert "sitelinks" not in minor


@patch("app.tools.wikidata.get_json", return_value={
    "error": {"code": "maxlag", "info": "Waiting for wdqs1014: 7.5 seconds lagged."},
    "servedby": "mw-api",
})
def test_api_level_error_is_detected_not_read_as_an_empty_result(mock_get):
    """Regression: Wikidata reports rejections as HTTP 200 with an `error` object.
    An unchecked .get("entities") turned a real failure into an indistinguishable
    empty result, which silently disabled the entire popularity signal."""
    _fetch_batch.cache_clear()
    assert sitelink_counts(["Q270983"]) == {}


def test_no_maxlag_parameter_is_sent():
    """maxlag throttles write traffic and rejects reads whenever the query service is
    lagged -- which it routinely is. Sending it disabled the signal in practice."""
    import pathlib as _p
    source = _p.Path("app/tools/wikidata.py").read_text()
    assert "maxlag" not in source.split('"""')[0] or '"maxlag"' not in source
