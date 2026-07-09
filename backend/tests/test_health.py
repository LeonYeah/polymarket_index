from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["timestamp_utc"].endswith("+00:00")


def test_wallet_timeline_route_is_registered() -> None:
    client = TestClient(create_app())
    paths = client.get("/openapi.json").json()["paths"]
    assert "/wallets/{wallet_address}/timeline" in paths
