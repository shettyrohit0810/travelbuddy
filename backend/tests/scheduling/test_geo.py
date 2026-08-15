from app.scheduling.models import Coordinates
from app.scheduling.geo import haversine_km, HaversineTravelTimeProvider


def test_haversine_km_same_point_is_zero():
    a = Coordinates(lat=12.34, lon=56.78)
    assert haversine_km(a, a) == 0.0


def test_haversine_km_one_degree_latitude_is_about_111km():
    a = Coordinates(lat=0.0, lon=0.0)
    b = Coordinates(lat=1.0, lon=0.0)
    distance = haversine_km(a, b)
    assert abs(distance - 111.19) < 0.5


def test_haversine_is_symmetric():
    a = Coordinates(lat=10.0, lon=20.0)
    b = Coordinates(lat=15.0, lon=25.0)
    assert abs(haversine_km(a, b) - haversine_km(b, a)) < 1e-9


def test_travel_time_provider_converts_distance_to_minutes_at_given_speed():
    a = Coordinates(lat=0.0, lon=0.0)
    b = Coordinates(lat=1.0, lon=0.0)
    provider = HaversineTravelTimeProvider(speed_kmh=20.0)
    minutes = provider.minutes_between(a, b)
    # ~111.19 km at 20 km/h = ~333.6 minutes
    assert abs(minutes - 333.6) < 2.0


def test_travel_time_provider_satisfies_the_protocol_structurally():
    from app.scheduling.ports import TravelTimeProvider
    provider = HaversineTravelTimeProvider()
    assert isinstance(provider, TravelTimeProvider)
