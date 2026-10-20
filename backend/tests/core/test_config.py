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


def test_assembled_dsn_names_the_driver_explicitly():
    """A bare `postgresql://` scheme lets SQLAlchemy pick the DBAPI, and which one it
    picks changed between 2.0 (psycopg2) and 2.1 (psycopg 3). With an unpinned
    `sqlalchemy>=2.0` requirement that resolves to whatever the install produced and
    raises ModuleNotFoundError when the engine is built -- which is past config
    validation, so nothing catches it earlier."""
    dsn = Settings._assemble_dsn(None, _FakeInfo({
        "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p",
        "POSTGRES_SERVER": "h", "POSTGRES_PORT": 5432, "POSTGRES_DB": "d",
    }))
    assert dsn.startswith("postgresql+psycopg2://")


def test_a_bare_explicit_url_is_pinned_to_the_installed_driver():
    bare = "postgresql://u:p@h:5432/d"
    assert Settings._assemble_dsn(bare, _FakeInfo({})) == "postgresql+psycopg2://u:p@h:5432/d"


def test_an_explicit_driver_choice_is_left_alone():
    """Naming a driver is an intent, not a default being relied on."""
    for url in ("postgresql+psycopg://u:p@h/d", "sqlite:///./x.db"):
        assert Settings._assemble_dsn(url, _FakeInfo({})) == url


class _FakeInfo:
    """Stands in for pydantic's ValidationInfo, which only `data` is read from here."""
    def __init__(self, data):
        self.data = data
