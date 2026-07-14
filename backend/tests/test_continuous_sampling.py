from __future__ import annotations

import asyncio
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from backend.app.analytics import continuous_sampling
from backend.app.collectors.incremental_wallet_data import IncrementalWalletCollector
from backend.app.core.config import Settings


class RecordingRepository:
    def __init__(self) -> None:
        self.params: list[dict[str, Any]] = []
        self.trades: list[dict[str, Any]] = []

    def record_raw_response(self, **kwargs: Any) -> None:
        self.params.append(dict(kwargs["request_params"]))

    def upsert_trades(self, trades: list[dict[str, Any]], _run_id: str) -> int:
        self.trades.extend(trades)
        return len(trades)


def test_incremental_wallet_poll_always_starts_at_zero_and_counts_only_new_rows() -> None:
    cutoff = datetime(2026, 7, 10, 10, tzinfo=UTC)
    payload = [
        {
            "id": "new",
            "proxyWallet": "0xabc",
            "conditionId": "condition-1",
            "asset": "token-1",
            "side": "BUY",
            "price": "0.55",
            "size": "10",
            "timestamp": int((cutoff + timedelta(seconds=30)).timestamp()),
        },
        {
            "id": "old",
            "proxyWallet": "0xabc",
            "conditionId": "condition-1",
            "asset": "token-1",
            "side": "BUY",
            "price": "0.50",
            "size": "5",
            "timestamp": int((cutoff - timedelta(seconds=30)).timestamp()),
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async def run() -> tuple[dict[str, int], RecordingRepository]:
        repository = RecordingRepository()
        collector = IncrementalWalletCollector(Settings(), engine=None)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            counters = await collector._poll_wallet(
                client,
                repository,  # type: ignore[arg-type]
                run_id="run-1",
                wallet="0xabc",
                cutoff=cutoff,
                page_limit=100,
                max_pages=2,
            )
        return counters, repository

    counters, repository = asyncio.run(run())
    assert counters == {"trade_rows": 2, "new_trade_rows": 1, "raw_responses": 1}
    assert repository.params[0]["offset"] == 0
    assert repository.params[0]["takerOnly"] == "false"
    assert len(repository.trades) == 2


class _ConnectionContext(AbstractContextManager[object]):
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


class _Engine:
    def begin(self) -> _ConnectionContext:
        return _ConnectionContext()


def test_continuous_cycle_keeps_paper_running_when_price_stage_degrades(
    monkeypatch: Any,
) -> None:
    class TargetRepository:
        def __init__(self, _connection: object) -> None:
            pass

        def fetch_sampling_token_ids(self, **_kwargs: object) -> list[str]:
            return ["token-1"]

    class Result:
        status = "succeeded"
        counters = {"rows": 1}

    class PaperResult:
        status = "completed"
        counters = {"orders": 1}

    monkeypatch.setattr(continuous_sampling, "_record_cycle_start", lambda *a, **k: None)
    monkeypatch.setattr(continuous_sampling, "_record_cycle_finish", lambda *a, **k: None)
    monkeypatch.setattr(continuous_sampling, "WalletDataRepository", TargetRepository)
    monkeypatch.setattr(continuous_sampling, "run_incremental_wallet_sync", lambda *a, **k: Result())
    monkeypatch.setattr(
        continuous_sampling,
        "run_price_archive_sync",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("clob unavailable")),
    )
    monkeypatch.setattr(continuous_sampling, "run_paper_trading", lambda *a, **k: PaperResult())

    result = continuous_sampling.run_continuous_sampling_cycle(Settings(), _Engine())

    assert result.status == "degraded"
    assert "clob unavailable" in result.errors["price_archive"]
    assert result.counters["paper_trading"] == {"orders": 1}
