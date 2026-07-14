from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import Engine

from backend.app.collectors.market_data import first_list, row_count
from backend.app.collectors.wallet_data import normalize_trade
from backend.app.core.config import Settings
from backend.app.core.run_context import new_run_id
from backend.app.db.wallet_repository import WalletDataRepository


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class IncrementalWalletResult:
    run_id: str
    status: str
    counters: dict[str, int]
    started_at: datetime
    finished_at: datetime
    warnings: list[str] = field(default_factory=list)


class IncrementalWalletCollector:
    """Poll newest trade pages for the research sampling and strict paper pools.

    Historical backfill checkpoints intentionally move toward older pages. This collector always
    starts at offset zero so a completed historical checkpoint cannot hide newly published trades.
    Research-pool membership only expands read-only collection; paper eligibility is checked later
    by the independent signal and risk-gate queries.
    """

    def __init__(self, settings: Settings, engine: Engine) -> None:
        self.settings = settings
        self.engine = engine

    async def run(
        self,
        *,
        research_wallet_limit: int = 25,
        page_limit: int = 100,
        max_pages: int = 2,
    ) -> IncrementalWalletResult:
        run_id = new_run_id("wallet_incremental")
        started_at = utc_now()
        counters = {
            "target_wallets": 0,
            "wallets_polled": 0,
            "trade_rows": 0,
            "new_trade_rows": 0,
            "raw_responses": 0,
            "failed_wallets": 0,
            "research_wallets": 0,
            "paper_eligible_wallets": 0,
        }
        warnings: list[str] = []
        params = {
            "research_wallet_limit": research_wallet_limit,
            "page_limit": page_limit,
            "max_pages": max_pages,
            "offset_policy": "always_start_at_zero",
            "taker_only": False,
        }
        with self.engine.begin() as connection:
            repository = WalletDataRepository(connection)
            repository.start_run(
                run_id,
                "wallet_trade_incremental",
                "polymarket",
                started_at,
                params,
            )
            try:
                wallets = repository.fetch_sampling_wallets(research_wallet_limit)
                counters["target_wallets"] = len(wallets)
                counters["research_wallets"] = sum(
                    1 for row in wallets if row.get("research_sampled")
                )
                counters["paper_eligible_wallets"] = sum(
                    1 for row in wallets if row.get("paper_eligible")
                )
                if not wallets:
                    warnings.append("no_sampling_wallets")
                async with httpx.AsyncClient(
                    timeout=self.settings.api_probe_timeout_seconds
                ) as client:
                    for target in wallets:
                        wallet = str(target["wallet_address"])
                        cutoff = repository.fetch_latest_trade_at(wallet)
                        try:
                            wallet_counters = await self._poll_wallet(
                                client,
                                repository,
                                run_id=run_id,
                                wallet=wallet,
                                cutoff=cutoff,
                                page_limit=page_limit,
                                max_pages=max_pages,
                            )
                            for key, value in wallet_counters.items():
                                counters[key] += value
                            counters["wallets_polled"] += 1
                        except Exception:  # noqa: BLE001 - isolate one wallet from the cycle.
                            counters["failed_wallets"] += 1
                finished_at = utc_now()
                status = "succeeded" if counters["failed_wallets"] == 0 else "degraded"
                repository.finish_run(run_id, status, finished_at, counters)
                return IncrementalWalletResult(
                    run_id,
                    status,
                    counters,
                    started_at,
                    finished_at,
                    warnings,
                )
            except Exception as exc:
                finished_at = utc_now()
                repository.finish_run(run_id, "failed", finished_at, counters, str(exc))
                raise

    async def _poll_wallet(
        self,
        client: httpx.AsyncClient,
        repository: WalletDataRepository,
        *,
        run_id: str,
        wallet: str,
        cutoff: datetime | None,
        page_limit: int,
        max_pages: int,
    ) -> dict[str, int]:
        counters = {"trade_rows": 0, "new_trade_rows": 0, "raw_responses": 0}
        for page in range(max(max_pages, 0)):
            offset = page * page_limit
            params = {
                "user": wallet,
                "limit": page_limit,
                "offset": offset,
                "takerOnly": "false",
            }
            payload, status_code, duration_ms = await self._fetch_json(client, params)
            repository.record_raw_response(
                run_id=run_id,
                source="data",
                endpoint="/trades",
                request_params=params,
                status_code=status_code,
                duration_ms=duration_ms,
                row_count=row_count(payload, "data"),
                captured_at=utc_now(),
                body=payload,
            )
            counters["raw_responses"] += 1
            if status_code >= 400:
                raise RuntimeError(f"data /trades returned HTTP {status_code}")
            rows = [row for row in first_list(payload, "data") if isinstance(row, Mapping)]
            trades = [
                trade
                for trade in (
                    normalize_trade(
                        row,
                        wallet_address=wallet,
                        run_id=run_id,
                        taker_only=False,
                    )
                    for row in rows
                )
                if trade is not None
            ]
            repository.upsert_trades(trades, run_id)
            counters["trade_rows"] += len(trades)
            counters["new_trade_rows"] += sum(
                1
                for trade in trades
                if cutoff is None
                or (
                    trade.get("trade_timestamp") is not None
                    and trade["trade_timestamp"] > cutoff
                )
            )
            timestamps = [
                trade["trade_timestamp"]
                for trade in trades
                if trade.get("trade_timestamp") is not None
            ]
            if len(rows) < page_limit or (cutoff is not None and timestamps and min(timestamps) <= cutoff):
                break
        return counters

    async def _fetch_json(
        self,
        client: httpx.AsyncClient,
        params: Mapping[str, Any],
    ) -> tuple[Any, int, int]:
        base_url = str(self.settings.polymarket_data_base_url).rstrip("/")
        last_error: Exception | None = None
        for attempt in range(self.settings.wallet_backfill_retry_attempts):
            started = time.perf_counter()
            try:
                response = await client.get(f"{base_url}/trades", params=dict(params))
                duration_ms = int((time.perf_counter() - started) * 1000)
                try:
                    payload: Any = response.json()
                except ValueError:
                    payload = {"raw_text": response.text[:4000]}
                if response.status_code < 500 and response.status_code != 429:
                    return payload, response.status_code, duration_ms
                last_error = RuntimeError(f"retryable HTTP {response.status_code}")
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
            if attempt + 1 < self.settings.wallet_backfill_retry_attempts:
                await asyncio.sleep(
                    self.settings.wallet_backfill_retry_base_seconds * (2**attempt)
                )
        raise RuntimeError(f"incremental trade request failed: {last_error}")


def run_incremental_wallet_sync(
    settings: Settings,
    engine: Engine,
    **kwargs: Any,
) -> IncrementalWalletResult:
    return asyncio.run(IncrementalWalletCollector(settings, engine).run(**kwargs))
