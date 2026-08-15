"""Configuration safety and parsing."""
import pytest

from app.core.config import Settings, settings


@pytest.mark.parametrize("raw,expected", [
    ("http://a.com,http://b.com", ["http://a.com", "http://b.com"]),
    (" http://a.com , http://b.com ", ["http://a.com", "http://b.com"]),
    ('["http://a.com","http://b.com"]', ["http://a.com", "http://b.com"]),
    ("http://a.com", ["http://a.com"]),
])
def test_cors_accepts_both_env_formats(raw, expected):
    """Compose files use the bare comma list, .env files copied from JSON use the
    array. Failing on either is a startup crash with an unhelpful message."""
    assert Settings._parse_cors(raw) == expected


def test_development_secrets_are_rejected_for_production():
    with pytest.raises(RuntimeError, match="development default"):
        settings.assert_production_ready()


def test_short_secrets_are_rejected(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "tooshort", raising=False)
    monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", "alsotooshort", raising=False)
    with pytest.raises(RuntimeError, match="32 bytes"):
        settings.assert_production_ready()


def test_identical_secrets_are_rejected(monkeypatch):
    """One secret for both means a stolen refresh token is accepted as an access token."""
    shared = "x" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", shared, raising=False)
    monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", shared, raising=False)
    with pytest.raises(RuntimeError, match="identical"):
        settings.assert_production_ready()


def test_distinct_long_secrets_pass(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "a" * 40, raising=False)
    monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", "b" * 40, raising=False)
    settings.assert_production_ready()
