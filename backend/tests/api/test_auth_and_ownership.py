"""Authentication and resource ownership.

The ownership tests are the important ones. Every trip route derives the owner from the
bearer token and filters on it; no route accepts a `user_id` argument, because a
client-supplied identifier is an assertion rather than proof.
"""


def test_health_reports_dependencies(client):
    body = client.get("/health").json()
    assert "database" in body and "llm_provider" in body


def test_register_then_login_issues_a_token(client):
    r = client.post("/api/v1/auth/register", json={
        "email": "a@example.com", "name": "A", "password": "StrongPass123"})
    assert r.status_code == 201 and "password" not in r.json()

    r = client.post("/api/v1/auth/login",
                    json={"email": "a@example.com", "password": "StrongPass123"})
    assert r.status_code == 200
    assert r.json()["access_token"] and r.json()["refresh_token"]


def test_duplicate_email_is_rejected(client, auth_headers):
    auth_headers(email="dup@example.com")
    r = client.post("/api/v1/auth/register", json={
        "email": "dup@example.com", "name": "Dup", "password": "StrongPass123"})
    assert r.status_code == 409


def test_wrong_password_and_unknown_email_look_identical(client, auth_headers):
    """Distinguishable responses let an attacker enumerate registered addresses."""
    auth_headers(email="real@example.com")
    wrong = client.post("/api/v1/auth/login",
                        json={"email": "real@example.com", "password": "WrongPass123"})
    unknown = client.post("/api/v1/auth/login",
                          json={"email": "ghost@example.com", "password": "WrongPass123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_short_password_is_rejected(client):
    r = client.post("/api/v1/auth/register",
                    json={"email": "b@example.com", "name": "B", "password": "short"})
    assert r.status_code == 422


def test_trip_routes_require_authentication(client):
    assert client.get("/api/v1/trips").status_code == 401
    assert client.post("/api/v1/trips", json={}).status_code == 401
    assert client.get("/api/v1/trips/1").status_code == 401
    assert client.delete("/api/v1/trips/1").status_code == 401


def test_an_access_token_is_not_accepted_as_a_refresh_token(client, auth_headers):
    headers = auth_headers(email="c@example.com")
    access = headers["Authorization"].removeprefix("Bearer ")
    assert client.post("/api/v1/auth/refresh", params={"refresh_token": access}).status_code == 401


def test_a_user_only_sees_their_own_trips(client, auth_headers):
    alice = auth_headers(email="alice@example.com")
    client.post("/api/v1/trips", headers=alice, json={
        "destination": "Goa", "days": 3, "travelers": 2, "plan_data": {"stops": 9}})

    bob = auth_headers(email="bob@example.com")
    assert client.get("/api/v1/trips", headers=bob).json()["total"] == 0
    assert client.get("/api/v1/trips", headers=alice).json()["total"] == 1


def test_reading_another_users_trip_returns_404_not_403(client, auth_headers):
    """403 would confirm the id exists for somebody else."""
    alice = auth_headers(email="alice2@example.com")
    trip_id = client.post("/api/v1/trips", headers=alice, json={
        "destination": "Goa", "days": 2, "travelers": 1, "plan_data": {}}).json()["id"]

    bob = auth_headers(email="bob2@example.com")
    assert client.get(f"/api/v1/trips/{trip_id}", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/trips/{trip_id}", headers=bob).status_code == 404
    # And Alice's trip survived Bob's delete attempt.
    assert client.get(f"/api/v1/trips/{trip_id}", headers=alice).status_code == 200


def test_owner_can_delete_their_trip(client, auth_headers):
    alice = auth_headers(email="alice3@example.com")
    trip_id = client.post("/api/v1/trips", headers=alice, json={
        "destination": "Kyoto", "days": 2, "travelers": 1, "plan_data": {}}).json()["id"]
    assert client.delete(f"/api/v1/trips/{trip_id}", headers=alice).status_code == 204
    assert client.get(f"/api/v1/trips/{trip_id}", headers=alice).status_code == 404
