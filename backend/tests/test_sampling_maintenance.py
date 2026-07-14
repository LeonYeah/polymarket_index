from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from backend.scripts import run_sampling_maintenance as maintenance


class Result:
    run_id = "run-1"
    status = "succeeded"
    counters = {"rows": 1}
    started_at = "start"
    finished_at = "finish"


class ConnectionContext(AbstractContextManager[object]):
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


class Engine:
    def begin(self) -> ConnectionContext:
        return ConnectionContext()


class SamplingRepository:
    def __init__(self, _connection: object) -> None:
        pass

    def fetch_sampling_wallets(self, research_limit: int) -> list[dict[str, object]]:
        assert research_limit == 25
        return [
            {"wallet_address": "0xresearch"},
            {"wallet_address": "0xpaper"},
        ]


def patch_sampling_repository(monkeypatch: Any) -> None:
    monkeypatch.setattr(maintenance, "WalletDataRepository", SamplingRepository)


def test_maintenance_discovers_wallets_before_pnl_and_smart_score(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    patch_sampling_repository(monkeypatch)

    def record(name: str):
        def run(*_args: Any, **kwargs: Any) -> Result:
            calls.append((name, kwargs))
            return Result()

        return run

    monkeypatch.setattr(maintenance, "run_market_ingestion_sync", record("market"))
    monkeypatch.setattr(maintenance, "run_wallet_backfill_sync", record("discovery"))
    monkeypatch.setattr(maintenance, "run_price_archive_sync", record("clv"))
    monkeypatch.setattr(maintenance, "run_pnl_calculation", record("pnl"))
    monkeypatch.setattr(maintenance, "run_smart_score", record("score"))

    results, errors = maintenance.run_sampling_maintenance(object(), Engine())

    assert errors == {}
    assert list(results) == ["market_ingestion", "wallet_discovery", "clv", "pnl", "smart_score"]
    assert [name for name, _ in calls] == ["market", "discovery", "clv", "pnl", "score"]
    discovery_kwargs = calls[1][1]
    assert discovery_kwargs == {
        "candidate_limit": 500,
        "leaderboard_limit": 150,
        "holder_candidate_limit": 250,
        "active_trader_limit": 250,
        "backfill_wallet_limit": 25,
        "page_limit": 100,
        "max_trade_pages": 2,
    }
    assert calls[2][1] == {
        "token_ids": [],
        "token_limit": 0,
        "include_price_history": False,
        "include_orderbook": False,
        "include_websocket": False,
        "include_clv": True,
        "clv_limit": 1000,
        "clv_wallet_addresses": ["0xresearch", "0xpaper"],
    }


def test_maintenance_continues_after_candidate_discovery_failure(monkeypatch: Any) -> None:
    calls: list[str] = []
    patch_sampling_repository(monkeypatch)

    monkeypatch.setattr(maintenance, "run_market_ingestion_sync", lambda *_a, **_k: Result())

    def fail_discovery(*_args: Any, **_kwargs: Any) -> Result:
        raise RuntimeError("candidate api unavailable")

    monkeypatch.setattr(maintenance, "run_wallet_backfill_sync", fail_discovery)
    monkeypatch.setattr(maintenance, "run_price_archive_sync", lambda *_a, **_k: Result())
    monkeypatch.setattr(
        maintenance,
        "run_pnl_calculation",
        lambda *_a, **_k: calls.append("pnl") or Result(),
    )
    monkeypatch.setattr(
        maintenance,
        "run_smart_score",
        lambda *_a, **_k: calls.append("score") or Result(),
    )

    results, errors = maintenance.run_sampling_maintenance(object(), Engine())

    assert calls == ["pnl", "score"]
    assert "candidate api unavailable" in errors["wallet_discovery"]
    assert "pnl" in results and "smart_score" in results


def test_maintenance_continues_after_clv_failure(monkeypatch: Any) -> None:
    calls: list[str] = []
    patch_sampling_repository(monkeypatch)

    monkeypatch.setattr(maintenance, "run_market_ingestion_sync", lambda *_a, **_k: Result())
    monkeypatch.setattr(maintenance, "run_wallet_backfill_sync", lambda *_a, **_k: Result())

    def fail_clv(*_args: Any, **_kwargs: Any) -> Result:
        raise RuntimeError("clv unavailable")

    monkeypatch.setattr(maintenance, "run_price_archive_sync", fail_clv)
    monkeypatch.setattr(
        maintenance,
        "run_pnl_calculation",
        lambda *_a, **_k: calls.append("pnl") or Result(),
    )
    monkeypatch.setattr(
        maintenance,
        "run_smart_score",
        lambda *_a, **_k: calls.append("score") or Result(),
    )

    results, errors = maintenance.run_sampling_maintenance(object(), Engine())

    assert calls == ["pnl", "score"]
    assert "clv unavailable" in errors["clv"]
    assert "pnl" in results and "smart_score" in results
