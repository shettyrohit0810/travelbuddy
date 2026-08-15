"""Place resolution, and the specific failures that motivated it.

Two real bugs are pinned here. Both produced confident, completely wrong plans rather
than errors, which is the failure mode worth regression-testing.
"""
from unittest.mock import patch

from app.tools.geocoding import ResolvedPlace, resolve_location, _shorten

NOMINATIM_GOA = [{
    "lat": "15.3004543", "lon": "74.0855134",
    "display_name": "Goa, India", "addresstype": "state",
}]

OPEN_METEO_GOA = {"results": [
    {"name": "Genoa", "country": "Italy", "latitude": 44.4, "longitude": 8.9, "population": 580097},
    {"name": "Goa", "country": "Philippines", "latitude": 13.7, "longitude": 123.5, "population": 20936},
]}


@patch("app.tools.geocoding.get_json", return_value=NOMINATIM_GOA)
def test_goa_resolves_to_the_indian_state(mock_get):
    """Regression: the previous geocoder returned Genoa, Italy for "Goa" -- an entire
    itinerary of Italian churches, labelled as an Indian beach trip."""
    resolve_location.cache_clear()
    place = resolve_location("Goa")
    assert place is not None
    assert "Goa" in place.display_name
    assert "Genoa" not in place.display_name
    assert 14.5 < place.lat < 16.0   # Indian state, not Liguria
    assert place.source == "nominatim"


@patch("app.tools.geocoding.get_json", return_value=[{
    "lat": "28.6", "lon": "77.2", "display_name": "Delhi, India", "addresstype": "region",
}])
def test_administrative_regions_resolve(mock_get):
    """Open-Meteo is a populated-places gazetteer and returns nothing for regions."""
    resolve_location.cache_clear()
    place = resolve_location("National Capital Region")
    assert place is not None
    assert place.kind == "region"


def test_falls_back_to_open_meteo_when_nominatim_is_unavailable():
    resolve_location.cache_clear()
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        if "nominatim" in url:
            raise RuntimeError("nominatim down")
        return OPEN_METEO_GOA

    with patch("app.tools.geocoding.get_json", side_effect=fake_get):
        place = resolve_location("Goa")

    assert place is not None
    assert place.source == "open-meteo"
    # Even in fallback, exact-name match must beat the more populous fuzzy hit.
    assert "Genoa" not in place.display_name


def test_returns_none_when_every_provider_fails():
    resolve_location.cache_clear()
    with patch("app.tools.geocoding.get_json", side_effect=RuntimeError("offline")):
        assert resolve_location("Kyoto") is None


def test_unresolvable_name_returns_none_rather_than_a_guess():
    resolve_location.cache_clear()
    with patch("app.tools.geocoding.get_json", return_value=[]):
        assert resolve_location("Zzqxwblahfake123") is None


def test_display_name_is_shortened_but_keeps_the_country():
    long_name = "Chikkamagaluru, Chikkamagaluru taluku, Chikkamagaluru, Karnataka, 577101, India"
    short = _shorten(long_name)
    assert short.startswith("Chikkamagaluru")
    assert short.endswith("India")
    assert len(short) < len(long_name)


def test_resolved_place_carries_coordinates_and_a_name():
    place = ResolvedPlace(lat=1.0, lon=2.0, display_name="Somewhere, Country")
    assert (place.lat, place.lon) == (1.0, 2.0)
    assert place.source == "nominatim"
