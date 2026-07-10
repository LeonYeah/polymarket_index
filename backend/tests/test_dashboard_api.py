from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api import alerts as alerts_api
from backend.app.api import markets as markets_api
from backend.app.api import wallets as wallets_api
from backend.app.main import create_app
from backend.scripts.benchmark_dashboard import percentile


class _ConnectionContext(AbstractContextManager[object]):
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


class _Engine:
    def begin(self) -> _ConnectionContext:
        return _ConnectionContext()


def test_wallet_top_contract_has_complete_pagination_units_and_utc(monkeypatch: Any) -> None:
    class Repository:
        def __init__(self, _connection: object) -> None:
            pass

        def fetch_top_wallets(self, **_kwargs: object) -> list[dict[str, object]]:
            return [
                {
                    "wallet_address": "0xabc",
                    "realized_pnl_180d": Decimal("12.34"),
                    "scored_at": datetime(2026, 7, 10, tzinfo=UTC),
                }
            ]

        def count_top_wallets(self, **_kwargs: object) -> int:
            return 150

    monkeypatch.setattr(wallets_api, "make_engine", lambda: _Engine())
    monkeypatch.setattr(wallets_api, "DashboardRepository", Repository)

    response = TestClient(create_app()).get("/wallets/top?limit=1&offset=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_units"] == "USDC"
    assert payload["pagination"] == {
        "limit": 1,
        "offset": 2,
        "returned": 1,
        "total": 150,
        "has_more": True,
    }
    assert payload["wallets"][0]["scored_at"].endswith("+00:00")


def test_market_list_contract_has_complete_pagination(monkeypatch: Any) -> None:
    class Repository:
        def __init__(self, _connection: object) -> None:
            pass

        def fetch_markets(self, **_kwargs: object) -> list[dict[str, str]]:
            return [{"condition_id": "market-1"}]

        def count_markets(self) -> int:
            return 500

    monkeypatch.setattr(markets_api, "make_engine", lambda: _Engine())
    monkeypatch.setattr(markets_api, "DashboardRepository", Repository)

    payload = TestClient(create_app()).get("/markets?limit=1&offset=499").json()

    assert payload["pagination"]["total"] == 500
    assert payload["pagination"]["has_more"] is False


def test_alert_generation_ack_and_resolution_contract(monkeypatch: Any) -> None:
    class Repository:
        status = "open"

        def __init__(self, _connection: object) -> None:
            pass

        def generate_alerts(self) -> dict[str, int]:
            return {"ingestion_delay": 1}

        def fetch_alerts(self, **_kwargs: object) -> list[dict[str, str]]:
            return [{"alert_id": "alert-1", "status": self.status}]

        def count_alerts(self, **_kwargs: object) -> int:
            return 1

        def update_alert_status(self, **kwargs: str) -> dict[str, str]:
            Repository.status = kwargs["status"]
            return {"alert_id": kwargs["alert_id"], "status": Repository.status}

    monkeypatch.setattr(alerts_api, "make_engine", lambda: _Engine())
    monkeypatch.setattr(alerts_api, "DashboardRepository", Repository)
    client = TestClient(create_app())

    generated = client.post("/alerts/generate")
    assert generated.status_code == 200
    assert generated.json()["generated_total"] == 1
    assert client.get("/alerts?generate=false").json()["pagination"]["total"] == 1

    acknowledged = client.patch(
        "/alerts/alert-1", json={"status": "ack", "operator": "test"}
    )
    assert acknowledged.json()["alert"]["status"] == "ack"
    resolved = client.patch(
        "/alerts/alert-1", json={"status": "resolved", "operator": "test"}
    )
    assert resolved.json()["alert"]["status"] == "resolved"


def test_api_errors_have_one_shape() -> None:
    client = TestClient(create_app())

    not_found = client.get("/missing")
    invalid = client.get("/markets?limit=0")

    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "http_404"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert isinstance(invalid.json()["error"]["details"], list)


def test_benchmark_percentile_uses_nearest_rank() -> None:
    assert percentile([1, 2, 3, 4, 5], 0.95) == 5
    assert percentile([1, 2, 3, 4, 5], 0.50) == 3
