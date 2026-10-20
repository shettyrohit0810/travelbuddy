"""Weather lookups are an enrichment, so no failure of theirs may be fatal.

`weather_lookup` documents that it returns an empty forecast rather than raising.
These tests hold it to that across the failure modes a donated public API actually
produces: a refused connection, a TLS handshake that never finishes, an HTTP error,
and a success payload of the wrong shape. A real benchmark run lost an entire trip
plan to the handshake case, because the geocode call inside it was unguarded.
"""
import urllib.error

import pytest

from app.tools import weather


def _uncached(monkeypatch):
    """Both functions are TTL-cached; clear them so each test makes its own call."""
    for fn in (weather._geocode, weather.weather_lookup):
        clear = getattr(fn, "cache_clear", None)
        if clear:
            clear()


@pytest.mark.parametrize("exc", [
    urllib.error.URLError("_ssl.c:993: The handshake operation timed out"),
    urllib.error.URLError("[Errno 61] Connection refused"),
    urllib.error.HTTPError("https://x", 503, "Service Unavailable", {}, None),
    TimeoutError("timed out"),
])
def test_a_geocode_transport_failure_is_not_fatal(monkeypatch, exc):
    _uncached(monkeypatch)
    monkeypatch.setattr(weather, "get_json", lambda *a, **k: (_ for _ in ()).throw(exc))

    result = weather.weather_lookup("Chikmagalur", 2)

    assert result["forecast"] == []
    assert result["average_temp_c"] is None
    assert result["location"] == "Chikmagalur"


def test_a_geocode_payload_of_the_wrong_shape_is_not_fatal(monkeypatch):
    """A proxy or error page returning a list, or a string, must not raise."""
    _uncached(monkeypatch)
    for payload in ([], "upstream error", None):
        _uncached(monkeypatch)
        monkeypatch.setattr(weather, "get_json", lambda *a, **k: payload)
        assert weather.weather_lookup("Chikmagalur", 2)["forecast"] == []


def test_a_match_missing_coordinates_is_not_fatal(monkeypatch):
    _uncached(monkeypatch)
    monkeypatch.setattr(weather, "get_json",
                        lambda *a, **k: {"results": [{"name": "Chikmagalur"}]})
    assert weather.weather_lookup("Chikmagalur", 2)["forecast"] == []


def test_a_forecast_failure_after_a_successful_geocode_is_not_fatal(monkeypatch):
    """The second call is the one that was already guarded; keep it that way."""
    _uncached(monkeypatch)
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"results": [{"latitude": 13.3, "longitude": 75.8}]}
        raise urllib.error.URLError("handshake timed out")

    monkeypatch.setattr(weather, "get_json", fake)
    assert weather.weather_lookup("Chikmagalur", 2)["forecast"] == []
    assert calls["n"] == 2, "the forecast call should have been attempted"
