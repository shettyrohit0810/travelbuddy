import logging
from app.core.cache import ttl_cache
from app.tools._http import get_json

logger = logging.getLogger("app.tools.weather")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@ttl_cache(seconds=1800)
def _geocode(location: str) -> tuple[float, float] | None:
    data = get_json(GEOCODING_URL, {"name": location, "count": 1})
    results = data.get("results") or []
    if not results:
        return None
    return results[0]["latitude"], results[0]["longitude"]


@ttl_cache(seconds=1800)
def weather_lookup(location: str, days: int = 7) -> dict:
    """
    Real forecast via Open-Meteo (free, no API key). Geocodes the location name to
    coordinates, then fetches a daily forecast. Returns an empty forecast (not fake
    data) if the location can't be resolved or the API call fails.
    """
    days = min(max(days, 1), 14)

    coords = _geocode(location)
    if coords is None:
        logger.warning(f"Open-Meteo geocoding found no match for location: {location!r}")
        return {"location": location, "days_checked": days, "average_temp_c": None, "forecast": []}

    lat, lon = coords
    try:
        data = get_json(FORECAST_URL, {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
            "forecast_days": days,
            "timezone": "auto",
        })
    except Exception as e:
        logger.error(f"Open-Meteo forecast request failed for {location!r}: {e}")
        return {"location": location, "days_checked": days, "average_temp_c": None, "forecast": []}

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    temp_max = daily.get("temperature_2m_max", [])
    temp_min = daily.get("temperature_2m_min", [])
    rain_prob = daily.get("precipitation_probability_max", [])
    weathercode = daily.get("weathercode", [])

    forecast = []
    total_temp = 0.0
    for i, date in enumerate(dates):
        hi = temp_max[i] if i < len(temp_max) else None
        lo = temp_min[i] if i < len(temp_min) else None
        avg = (hi + lo) / 2 if hi is not None and lo is not None else None
        if avg is not None:
            total_temp += avg
        forecast.append({
            "day": i + 1,
            "date": date,
            "temp_c": round(avg) if avg is not None else None,
            "condition": _condition_label(weathercode[i] if i < len(weathercode) else None),
            "rain_probability": f"{rain_prob[i]}%" if i < len(rain_prob) and rain_prob[i] is not None else "0%",
        })

    return {
        "location": location,
        "days_checked": len(forecast),
        "average_temp_c": round(total_temp / len(forecast)) if forecast else None,
        "forecast": forecast,
    }


def _condition_label(weathercode: int | None) -> str:
    # WMO weather interpretation codes (Open-Meteo docs)
    if weathercode is None:
        return "Unknown"
    if weathercode == 0:
        return "Clear"
    if weathercode in (1, 2, 3):
        return "Partly Cloudy"
    if weathercode in (45, 48):
        return "Foggy"
    if weathercode in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "Rainy"
    if weathercode in (71, 73, 75, 77, 85, 86):
        return "Snowy"
    if weathercode in (95, 96, 99):
        return "Stormy"
    return "Sunny"
