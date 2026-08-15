"""Application settings.

Two conventions worth knowing before editing:

1. `BACKEND_CORS_ORIGINS` is annotated `NoDecode` so this module owns all parsing.
   pydantic-settings otherwise JSON-decodes complex types before validators run, which
   makes the plain `a,b` form crash at startup. The validator accepts both forms.
2. LLM providers are resolved by capability, not by name. Everything supported speaks
   the OpenAI wire format, so adding one is a table entry in `core/llm.py`.
"""
from typing import Annotated, List, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "TravelBuddy"
    API_V1_STR: str = "/api/v1"

    BACKEND_CORS_ORIGINS: Annotated[List[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors(cls, value: Union[str, List[str]]) -> List[str]:
        """Accept both `a,b` and `["a","b"]`.

        Both forms appear in the wild -- docker-compose files tend to use the bare
        comma list, .env files copied from JSON examples use the array -- and silently
        failing on either is a startup crash with an unhelpful `list_type` message.
        """
        if isinstance(value, list):
            return value
        text = str(value).strip()
        if text.startswith("["):
            import json
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "travelbuddy"
    POSTGRES_PORT: str = "5432"
    DATABASE_URL: str | None = None

    # 32 bytes minimum: PyJWT warns below that for HMAC-SHA256, and a short key
    # weakens the signature rather than merely being untidy. These defaults are
    # development-only and `assert_production_ready()` refuses to let them ship.
    SECRET_KEY: str = "dev-only-access-secret-not-for-production-use"
    REFRESH_SECRET_KEY: str = "dev-only-refresh-secret-not-for-production-use"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Any one of these enables the agent layer. All speak the OpenAI wire format.
    OPENAI_API_KEY: str | None = None
    XAI_API_KEY: str | None = None

    # POI grounding needs no key: OpenStreetMap Overpass and Open-Meteo are both open.
    OPENTRIPMAP_API_KEY: str | None = None

    def assert_production_ready(self) -> None:
        """Fail loudly if the app is about to run with development secrets.

        Called from the entrypoint rather than at import time so tests and local runs
        stay frictionless while a real deployment cannot silently sign tokens with a
        key that is published in this repository.
        """
        problems = []
        for name in ("SECRET_KEY", "REFRESH_SECRET_KEY"):
            value = getattr(self, name)
            if value.startswith("dev-only-"):
                problems.append(f"{name} is still the development default")
            if len(value.encode()) < 32:
                problems.append(f"{name} is shorter than the 32 bytes HMAC-SHA256 needs")
        if self.SECRET_KEY == self.REFRESH_SECRET_KEY:
            problems.append("SECRET_KEY and REFRESH_SECRET_KEY are identical, so a "
                            "refresh token would be accepted as an access token")
        if problems:
            raise RuntimeError("Unsafe configuration: " + "; ".join(problems))

    @property
    def LLM_PROVIDER(self) -> str | None:
        """Which provider is configured, or None. Deterministic order, not preference."""
        if self.XAI_API_KEY:
            return "xai"
        if self.OPENAI_API_KEY:
            return "groq" if self.OPENAI_API_KEY.startswith("gsk_") else "openai"
        return None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _assemble_dsn(cls, value: str | None, info) -> str:
        if value:
            return value
        import urllib.parse
        data = info.data
        password = urllib.parse.quote_plus(data.get("POSTGRES_PASSWORD", ""))
        return (
            f"postgresql://{data.get('POSTGRES_USER')}:{password}"
            f"@{data.get('POSTGRES_SERVER')}:{data.get('POSTGRES_PORT')}/{data.get('POSTGRES_DB')}"
        )

    model_config = SettingsConfigDict(
        case_sensitive=True, env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
