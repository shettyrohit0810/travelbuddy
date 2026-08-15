import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _force_live_poi_path(monkeypatch):
    """These tests cover the parsing/query logic, so they must run the live path even
    when TRAVELBUDDY_DISABLE_LIVE_POI is set in the environment (CI sets it on push).
    Without this the escape hatch short-circuits before the mocks and every assertion
    silently sees an empty result."""
    monkeypatch.delenv("TRAVELBUDDY_DISABLE_LIVE_POI", raising=False)

from app.tools.poi_overpass import overpass_poi_search, _cost_for, _notability_score, _coords_of
from app.scheduling.costs import StaticCostEstimator, ACTIVITY_COST_BY_CATEGORY

EST = StaticCostEstimator()


# --- cost policy: the bug class this must never reintroduce -------------------

def test_missing_fee_tag_is_not_treated_as_free():
    """OSM omits `fee` on most features. Absent must mean 'probably costs something',
    or unpriced stops slip past the budget ceiling as zero-cost."""
    cost = _cost_for({}, "museums", EST)
    assert cost > 0.0
    assert cost == ACTIVITY_COST_BY_CATEGORY["museums"]


def test_explicit_fee_no_is_free():
    assert _cost_for({"fee": "no"}, "museums", EST) == 0.0


def test_fee_yes_without_charge_uses_category_rate():
    assert _cost_for({"fee": "yes"}, "historic", EST) == ACTIVITY_COST_BY_CATEGORY["historic"]


def test_charge_tag_is_ignored_rather_than_mixing_currencies():
    """`charge` values carry mixed currencies ("500 JPY", "£3.50"). Using them without
    FX would silently corrupt a single-currency budget total."""
    assert _cost_for({"fee": "yes", "charge": "500 JPY"}, "museums", EST) == ACTIVITY_COST_BY_CATEGORY["museums"]


# --- notability proxy ---------------------------------------------------------

def test_notability_prefers_wikidata_linked_features():
    linked = _notability_score({"wikidata": "Q123", "wikipedia": "en:Foo"})
    partial = _notability_score({"wikidata": "Q123"})
    plain = _notability_score({})
    assert linked > partial > plain
    assert 0.0 <= plain and linked <= 5.0


# --- coordinate extraction ----------------------------------------------------

def test_coords_from_node_and_from_way_center():
    assert _coords_of({"lat": 1.0, "lon": 2.0}) == (1.0, 2.0)
    assert _coords_of({"center": {"lat": 3.0, "lon": 4.0}}) == (3.0, 4.0)
    assert _coords_of({"type": "way"}) is None


# --- end-to-end shape with mocked network ------------------------------------

MOCK_OVERPASS = {
    "elements": [
        {"lat": 35.0, "lon": 135.0, "tags": {"name": "Big Temple", "historic": "temple", "wikidata": "Q1", "wikipedia": "en:Big"}},
        {"type": "way", "center": {"lat": 35.01, "lon": 135.01}, "tags": {"name": "City Park", "leisure": "park", "fee": "no"}},
        {"lat": 35.02, "lon": 135.02, "tags": {"name": "Big Temple"}},          # duplicate name
        {"lat": 35.03, "lon": 135.03, "tags": {"historic": "yes"}},              # no name
        {"type": "way", "tags": {"name": "No Coords Place", "tourism": "museum"}},  # no coords
    ]
}


@patch("app.tools.poi_overpass._query_overpass", return_value=MOCK_OVERPASS)
@patch("app.tools.poi_overpass._geocode", return_value=(35.0, 135.0, "Testville, Japan", 8000))
def test_overpass_search_dedupes_and_skips_unusable_entries(mock_geo, mock_post):
    overpass_poi_search.cache_clear()
    result = overpass_poi_search("Testville")

    names = [a["name"] for a in result["activities"]]
    assert names.count("Big Temple") == 1          # deduped
    assert "No Coords Place" not in names          # no coordinates -> skipped
    assert result["results_count"] == 2
    assert result["source"] == "overpass"
    for a in result["activities"]:
        assert a["lat"] is not None and a["lon"] is not None
        assert a["estimated_cost"] >= 0.0

    park = next(a for a in result["activities"] if a["name"] == "City Park")
    assert park["estimated_cost"] == 0.0           # fee=no
    temple = next(a for a in result["activities"] if a["name"] == "Big Temple")
    assert temple["estimated_cost"] > 0.0          # no fee tag -> not free


@patch("app.tools.poi_overpass._geocode", return_value=None)
def test_overpass_search_returns_empty_when_geocoding_fails(mock_geo):
    overpass_poi_search.cache_clear()
    result = overpass_poi_search("Zzqxwblahfake123")
    assert result["activities"] == []
    assert result["results_count"] == 0


@patch("app.tools.poi_overpass._query_overpass", return_value=None)
@patch("app.tools.poi_overpass._geocode", return_value=(35.0, 135.0, "Testville, Japan", 8000))
def test_overpass_search_degrades_on_rate_limit_rather_than_fabricating(mock_geo, mock_post):
    overpass_poi_search.cache_clear()
    result = overpass_poi_search("Testville")
    assert result["activities"] == []
