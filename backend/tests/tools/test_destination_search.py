from unittest.mock import patch

from app.tools.destination_search import destination_search


MOCK_GEOCODE_RESPONSE = {"lat": 35.0, "lon": 135.0, "status": "ok"}

MOCK_RADIUS_RESPONSE = [
    {"name": "Real Temple", "kinds": "historic,religion", "rate": "3", "point": {"lat": 35.001, "lon": 135.001}},
    {"name": "No Coords Place", "kinds": "natural", "rate": "2", "point": {}},
    {"name": "", "kinds": "shops", "rate": "1", "point": {"lat": 35.002, "lon": 135.002}},
]


@patch("app.tools.destination_search.get_json")
@patch("app.tools.destination_search.settings")
def test_destination_search_captures_coordinates_and_skips_incomplete_places(mock_settings, mock_get_json):
    mock_settings.OPENTRIPMAP_API_KEY = "fake-key"
    mock_get_json.side_effect = [MOCK_GEOCODE_RESPONSE, MOCK_RADIUS_RESPONSE]

    # destination_search() calls _geocode() internally, and _geocode is ALSO
    # independently @ttl_cache-decorated -- clearing only the outer cache isn't
    # enough, or a stale cached geocode result from an earlier test run could mask
    # this test's mocked response.
    from app.tools.destination_search import _geocode
    destination_search.cache_clear()
    _geocode.cache_clear()
    result = destination_search("Testville")

    assert result["results_count"] == 1
    activity = result["activities"][0]
    assert activity["name"] == "Real Temple"
    assert activity["lat"] == 35.001
    assert activity["lon"] == 135.001
