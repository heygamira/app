"""Health endpoint, error envelope and correlation ids."""

from __future__ import annotations

from tests.conftest import auth


async def test_health_reports_database_ok(client):
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert response.headers["X-Request-Id"]


async def test_missing_token_returns_the_standard_error_shape(client):
    response = await client.get("/api/v1/me")

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "unauthenticated"
    assert error["request_id"] == response.headers["X-Request-Id"]


async def test_malformed_token_is_rejected(client):
    response = await client.get(
        "/api/v1/me", headers={"Authorization": "Bearer not-a-dev-token"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_validation_errors_do_not_echo_submitted_values(client):
    await client.post("/api/v1/families", json={"name": "Test"}, headers=auth("owner"))

    response = await client.post(
        "/api/v1/families", json={"name": ""}, headers=auth("owner")
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["details"]["fields"][0]["field"] == "name"
    # The rejected input must not be reflected back.
    assert "input" not in error["details"]["fields"][0]


async def test_inbound_request_id_is_echoed(client):
    response = await client.get("/health", headers={"X-Request-Id": "trace-me"})

    assert response.headers["X-Request-Id"] == "trace-me"
