"""Shared fixtures.

API tests run against an in-memory SQLite database rather than Postgres. The models use
JSONB, which SQLite lacks, so the column declares a JSON variant for that dialect; the
production dialect is unchanged. The tradeoff is deliberate: these tests assert
authorisation and routing behaviour, which is dialect-independent, and requiring a live
Postgres to check "does an unauthenticated request get 401" would mean CI skips it.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def auth_headers(client):
    def _make(email="user@example.com", password="StrongPass123", name="User"):
        client.post("/api/v1/auth/register",
                    json={"email": email, "name": name, "password": password})
        token = client.post("/api/v1/auth/login",
                            json={"email": email, "password": password}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return _make
