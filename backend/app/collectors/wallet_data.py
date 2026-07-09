from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import Engine

from backend.app.collectors.market_data import (
    first_list,
    parse_datetime,
    parse_decimal,
    row_count,
)
from backend.app.core.config import Settings
from backend.app.core.run_context import new_run_id
from backend.app.db.wallet_repository import WalletDataRepository


LEADERBOARD_PERIODS = ("DAY", "WEEK", "MONTH", "ALL")


@dataclass(frozen=True)
class WalletBackfillResult:
    run_id: str
    status: str
    counters: dict[str, int]
    started_at: datetime
    finished_at: datetime
    warnings: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_wallet_address(value: Any) -> str | None:
    if value is None:
        return None
    wallet = str(value).strip().lower()
    if not wallet or wallet in {"none", "null"}:
        return None
    return wallet


def stable_hash(parts: list[Any]) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def first_wallet(raw: Mapping[str, Any]) -> str | None:
    for key in ("proxyWallet", "wallet", "maker", "taker", "user"):
        wallet = normalize_wallet_address(raw.get(key))
        if wallet:
            return wallet
    return None


def wallet_row(
    wallet_address: str,
    *,
    run_id: str,
    observed_at: datetime | None,
    raw: Mapping[str, Any],
    source: str = "data",
) -> dict[str, Any]:
    return {
        "wallet_address": wallet_address,
        "first_seen_at": observed_at,
        "last_seen_at": observed_at,
        "raw": dict(raw),
        "source": source,
        "ingestion_run_id": run_id,
    }


def normalize_leaderboard_candidates(
    payload: Any,
    *,
    period: str,
    run_id: str,
    discovered_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    wallets = []
    candidates = []
    for row in first_list(payload, "data"):
        if not isinstance(row, Mapping):
            continue
        wallet_address = first_wallet(row)
        if not wallet_address:
            continue
        wallets.append(wallet_row(wallet_address, run_id=run_id, observed_at=discovered_at, raw=row))
        candidates.append(
            {
                "wallet_address": wallet_address,
                "seed_source": "leaderboard",
                "seed_ref": period,
                "discovered_at": discovered_at,
                "rank": _parse_int(row.get("rank")),
                "score": parse_decimal(row.get("pnl")) or parse_decimal(row.get("vol")),
                "raw": dict(row) | {"period": period},
                "source": "data",
                "ingestion_run_id": run_id,
            }
        )
    return wallets, candidates


def normalize_holder_candidate_rows(
    rows: list[Mapping[str, Any]],
    *,
    run_id: str,
    discovered_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    wallets = []
    candidates = []
    for row in rows:
        wallet_address = normalize_wallet_address(row.get("wallet_address"))
        if not wallet_address:
            continue
        observed_at = row.get("last_seen_at")
        if not isinstance(observed_at, datetime):
            observed_at = discovered_at
        raw = dict(row)
        wallets.append(wallet_row(wallet_address, run_id=run_id, observed_at=observed_at, raw=raw))
        candidates.append(
            {
                "wallet_address": wallet_address,
                "seed_source": "holder",
                "seed_ref": str(row.get("seed_ref")) if row.get("seed_ref") else None,
                "discovered_at": discovered_at,
                "rank": None,
                "score": parse_decimal(row.get("token_count")),
                "raw": raw,
                "source": "db.market_holders",
                "ingestion_run_id": run_id,
            }
        )
    return wallets, candidates


def normalize_active_trader_candidates(
    payload: Any,
    *,
    run_id: str,
    discovered_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen: set[str] = set()
    wallets = []
    candidates = []
    for row in first_list(payload, "data"):
        if not isinstance(row, Mapping):
            continue
        wallet_address = first_wallet(row)
        if not wallet_address or wallet_address in seen:
            continue
        seen.add(wallet_address)
        observed_at = parse_datetime(row.get("timestamp")) or discovered_at
        wallets.append(wallet_row(wallet_address, run_id=run_id, observed_at=observed_at, raw=row))
        seed_ref = row.get("conditionId") or row.get("transactionHash")
        candidates.append(
            {
                "wallet_address": wallet_address,
                "seed_source": "active_trader",
                "seed_ref": str(seed_ref) if seed_ref else None,
                "discovered_at": discovered_at,
                "rank": None,
                "score": _trade_notional(row),
                "raw": dict(row),
                "source": "data",
                "ingestion_run_id": run_id,
            }
        )
    return wallets, candidates


def normalize_trade(
    raw: Mapping[str, Any],
    *,
    wallet_address: str | None,
    run_id: str,
    taker_only: bool,
) -> dict[str, Any] | None:
    wallet = normalize_wallet_address(wallet_address) or first_wallet(raw)
    if not wallet:
        return None
    price = parse_decimal(raw.get("price"))
    size = parse_decimal(raw.get("size"))
    notional = price * size if price is not None and size is not None else None
    condition_id = raw.get("conditionId") or raw.get("condition_id") or raw.get("market")
    token_id = raw.get("asset") or raw.get("assetId") or raw.get("token_id")
    timestamp = parse_datetime(raw.get("timestamp") or raw.get("createdAt"))
    transaction_hash = raw.get("transactionHash") or raw.get("transaction_hash")
    api_trade_id = raw.get("id") or raw.get("tradeId")
    trade_uid = stable_hash(
        [
            wallet,
            condition_id,
            token_id,
            raw.get("side"),
            price,
            size,
            timestamp,
            transaction_hash,
            api_trade_id,
            taker_only,
        ]
    )
    return {
        "trade_uid": trade_uid,
        "api_trade_id": str(api_trade_id) if api_trade_id is not None else None,
        "wallet_address": wallet,
        "proxy_wallet": normalize_wallet_address(raw.get("proxyWallet")),
        "condition_id": str(condition_id) if condition_id is not None else None,
        "token_id": str(token_id) if token_id is not None else None,
        "side": str(raw.get("side")) if raw.get("side") is not None else None,
        "price": price,
        "size": size,
        "notional": notional,
        "trade_timestamp": timestamp,
        "transaction_hash": str(transaction_hash) if transaction_hash is not None else None,
        "taker_only": taker_only,
        "raw": dict(raw),
        "source": "data",
        "ingestion_run_id": run_id,
    }


def normalize_current_position(
    raw: Mapping[str, Any],
    *,
    wallet_address: str,
    run_id: str,
    snapshot_at: datetime,
) -> dict[str, Any] | None:
    wallet = normalize_wallet_address(raw.get("proxyWallet")) or normalize_wallet_address(wallet_address)
    if not wallet:
        return None
    condition_id = raw.get("conditionId") or raw.get("condition_id")
    token_id = raw.get("asset") or raw.get("assetId")
    position_uid = stable_hash(["current", wallet, condition_id, token_id])
    return {
        "position_uid": position_uid,
        "wallet_address": wallet,
        "condition_id": str(condition_id) if condition_id is not None else None,
        "token_id": str(token_id) if token_id is not None else None,
        "outcome": str(raw.get("outcome")) if raw.get("outcome") is not None else None,
        "size": parse_decimal(raw.get("size")),
        "avg_price": parse_decimal(raw.get("avgPrice")),
        "initial_value": parse_decimal(raw.get("initialValue")),
        "current_value": parse_decimal(raw.get("currentValue")),
        "cash_pnl": parse_decimal(raw.get("cashPnl")),
        "realized_pnl": parse_decimal(raw.get("realizedPnl")),
        "cur_price": parse_decimal(raw.get("curPrice")),
        "redeemable": raw.get("redeemable"),
        "mergeable": raw.get("mergeable"),
        "title": raw.get("title"),
        "slug": raw.get("slug"),
        "event_slug": raw.get("eventSlug"),
        "end_date": parse_datetime(raw.get("endDate")),
        "snapshot_at": snapshot_at,
        "raw": dict(raw),
        "source": "data",
        "ingestion_run_id": run_id,
    }


def normalize_closed_position(
    raw: Mapping[str, Any],
    *,
    wallet_address: str,
    run_id: str,
) -> dict[str, Any] | None:
    wallet = normalize_wallet_address(raw.get("proxyWallet")) or normalize_wallet_address(wallet_address)
    if not wallet:
        return None
    condition_id = raw.get("conditionId") or raw.get("condition_id")
    token_id = raw.get("asset") or raw.get("assetId")
    closed_at = parse_datetime(raw.get("timestamp"))
    position_uid = stable_hash(["closed", wallet, condition_id, token_id, closed_at])
    return {
        "position_uid": position_uid,
        "wallet_address": wallet,
        "condition_id": str(condition_id) if condition_id is not None else None,
        "token_id": str(token_id) if token_id is not None else None,
        "outcome": str(raw.get("outcome")) if raw.get("outcome") is not None else None,
        "avg_price": parse_decimal(raw.get("avgPrice")),
        "total_bought": parse_decimal(raw.get("totalBought")),
        "realized_pnl": parse_decimal(raw.get("realizedPnl")),
        "cur_price": parse_decimal(raw.get("curPrice")),
        "title": raw.get("title"),
        "slug": raw.get("slug"),
        "event_slug": raw.get("eventSlug"),
        "end_date": parse_datetime(raw.get("endDate")),
        "closed_at": closed_at,
        "raw": dict(raw),
        "source": "data",
        "ingestion_run_id": run_id,
    }


class WalletDataBackfill:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self.settings = settings
        self.engine = engine

    async def run(
        self,
        *,
        candidate_limit: int | None = None,
        leaderboard_limit: int | None = None,
        holder_candidate_limit: int | None = None,
        active_trader_limit: int | None = None,
        backfill_wallet_limit: int | None = None,
        page_limit: int | None = None,
        max_trade_pages: int | None = None,
    ) -> WalletBackfillResult:
        run_id = new_run_id("wallet_backfill")
        started_at = utc_now()
        candidate_limit = self.settings.wallet_candidate_limit if candidate_limit is None else candidate_limit
        leaderboard_limit = (
            self.settings.wallet_leaderboard_limit if leaderboard_limit is None else leaderboard_limit
        )
        holder_candidate_limit = (
            self.settings.wallet_holder_candidate_limit
            if holder_candidate_limit is None
            else holder_candidate_limit
        )
        active_trader_limit = (
            self.settings.wallet_active_trader_limit
            if active_trader_limit is None
            else active_trader_limit
        )
        backfill_wallet_limit = (
            self.settings.wallet_backfill_wallet_limit
            if backfill_wallet_limit is None
            else backfill_wallet_limit
        )
        page_limit = self.settings.wallet_backfill_page_limit if page_limit is None else page_limit
        max_trade_pages = (
            self.settings.wallet_backfill_max_trade_pages
            if max_trade_pages is None
            else max_trade_pages
        )
        params = {
            "candidate_limit": candidate_limit,
            "leaderboard_limit": leaderboard_limit,
            "holder_candidate_limit": holder_candidate_limit,
            "active_trader_limit": active_trader_limit,
            "backfill_wallet_limit": backfill_wallet_limit,
            "page_limit": page_limit,
            "max_trade_pages": max_trade_pages,
            "retry_attempts": self.settings.wallet_backfill_retry_attempts,
            "retry_base_seconds": self.settings.wallet_backfill_retry_base_seconds,
            "leaderboard_periods": list(LEADERBOARD_PERIODS),
            "trades_taker_only": False,
        }
        counters: dict[str, int] = {
            "wallets": 0,
            "candidates": 0,
            "leaderboard_rows": 0,
            "holder_candidates": 0,
            "active_trader_candidates": 0,
            "wallets_backfilled": 0,
            "trades": 0,
            "current_positions": 0,
            "closed_positions": 0,
            "raw_responses": 0,
            "checkpoints": 0,
            "failed_wallets": 0,
            "distinct_candidate_wallets": 0,
            "fully_backfilled_wallets": 0,
            "trade_exhausted_wallets": 0,
        }
        warnings: list[str] = []

        with self.engine.begin() as connection:
            repository = WalletDataRepository(connection)
            repository.start_run(run_id, "wallet_discovery_backfill", "polymarket", started_at, params)
            try:
                async with httpx.AsyncClient(timeout=self.settings.api_probe_timeout_seconds) as client:
                    for period in LEADERBOARD_PERIODS:
                        payload = await self._fetch_json(
                            client,
                            repository,
                            run_id,
                            "/v1/leaderboard",
                            {"limit": leaderboard_limit, "period": period},
                            "data",
                        )
                        counters["raw_responses"] += 1
                        wallets, candidates = normalize_leaderboard_candidates(
                            payload,
                            period=period,
                            run_id=run_id,
                            discovered_at=utc_now(),
                        )
                        counters["leaderboard_rows"] += len(candidates)
                        counters["wallets"] += repository.upsert_wallets(wallets, run_id)
                        counters["candidates"] += repository.upsert_candidates(candidates, run_id)

                    holder_rows = repository.fetch_holder_candidates(holder_candidate_limit)
                    wallets, candidates = normalize_holder_candidate_rows(
                        holder_rows,
                        run_id=run_id,
                        discovered_at=utc_now(),
                    )
                    counters["holder_candidates"] += len(candidates)
                    counters["wallets"] += repository.upsert_wallets(wallets, run_id)
                    counters["candidates"] += repository.upsert_candidates(candidates, run_id)

                    active_payload = await self._fetch_json(
                        client,
                        repository,
                        run_id,
                        "/trades",
                        {"limit": active_trader_limit, "takerOnly": "false"},
                        "data",
                    )
                    counters["raw_responses"] += 1
                    wallets, candidates = normalize_active_trader_candidates(
                        active_payload,
                        run_id=run_id,
                        discovered_at=utc_now(),
                    )
                    counters["active_trader_candidates"] += len(candidates)
                    counters["wallets"] += repository.upsert_wallets(wallets, run_id)
                    counters["candidates"] += repository.upsert_candidates(candidates, run_id)

                    backfill_wallets = repository.fetch_candidate_wallets(
                        min(candidate_limit, backfill_wallet_limit)
                    )
                    for wallet_address in backfill_wallets:
                        try:
                            wallet_counters = await self._backfill_wallet(
                                client,
                                repository,
                                run_id,
                                wallet_address,
                                page_limit,
                                max_trade_pages,
                            )
                            for key, value in wallet_counters.items():
                                counters[key] += value
                            counters["wallets_backfilled"] += 1
                        except Exception as exc:  # noqa: BLE001 - record wallet-level failure and continue.
                            repository.update_checkpoint(
                                wallet_address=wallet_address,
                                endpoint="/wallet-backfill",
                                taker_only=False,
                                next_offset=0,
                                status="failed",
                                run_id=run_id,
                                last_error=f"{type(exc).__name__}: {exc}",
                            )
                            counters["failed_wallets"] += 1
                            counters["checkpoints"] += 1

                    repository.refresh_wallet_activity(backfill_wallets, run_id)

                finished_at = utc_now()
                counters["distinct_candidate_wallets"] = repository.count_candidate_wallets()
                counters["fully_backfilled_wallets"] = repository.count_backfilled_wallets()
                counters["trade_exhausted_wallets"] = repository.count_trade_exhausted_wallets()
                if counters["distinct_candidate_wallets"] < candidate_limit:
                    warnings.append("candidate_pool_below_target")
                if counters["fully_backfilled_wallets"] < backfill_wallet_limit:
                    warnings.append("fully_backfilled_wallets_below_target")
                repository.finish_run(run_id, "succeeded", finished_at, counters)
                return WalletBackfillResult(
                    run_id,
                    "succeeded",
                    counters,
                    started_at,
                    finished_at,
                    warnings,
                )
            except Exception as exc:
                finished_at = utc_now()
                repository.finish_run(run_id, "failed", finished_at, counters, str(exc))
                raise

    async def _backfill_wallet(
        self,
        client: httpx.AsyncClient,
        repository: WalletDataRepository,
        run_id: str,
        wallet_address: str,
        page_limit: int,
        max_trade_pages: int,
    ) -> dict[str, int]:
        counters = {
            "trades": 0,
            "current_positions": 0,
            "closed_positions": 0,
            "raw_responses": 0,
            "checkpoints": 0,
        }
        taker_only = False
        offset = repository.get_checkpoint_offset(wallet_address, "/trades", taker_only)
        for _ in range(max_trade_pages):
            payload = await self._fetch_json(
                client,
                repository,
                run_id,
                "/trades",
                {
                    "user": wallet_address,
                    "limit": page_limit,
                    "offset": offset,
                    "takerOnly": "false",
                },
                "data",
            )
            counters["raw_responses"] += 1
            rows = [row for row in first_list(payload, "data") if isinstance(row, Mapping)]
            trades = [
                trade
                for trade in (
                    normalize_trade(row, wallet_address=wallet_address, run_id=run_id, taker_only=False)
                    for row in rows
                )
                if trade
            ]
            counters["trades"] += repository.upsert_trades(trades, run_id)
            offset += len(rows)
            status = "exhausted" if len(rows) < page_limit else "running"
            repository.update_checkpoint(
                wallet_address=wallet_address,
                endpoint="/trades",
                taker_only=taker_only,
                next_offset=offset,
                status=status,
                run_id=run_id,
            )
            counters["checkpoints"] += 1
            if len(rows) < page_limit:
                break

        positions_payload = await self._fetch_json(
            client,
            repository,
            run_id,
            "/positions",
            {"user": wallet_address, "limit": page_limit},
            "data",
        )
        counters["raw_responses"] += 1
        current_positions = [
            position
            for position in (
                normalize_current_position(
                    row,
                    wallet_address=wallet_address,
                    run_id=run_id,
                    snapshot_at=utc_now(),
                )
                for row in first_list(positions_payload, "data")
                if isinstance(row, Mapping)
            )
            if position
        ]
        counters["current_positions"] += repository.upsert_current_positions(
            current_positions, run_id
        )
        repository.update_checkpoint(
            wallet_address=wallet_address,
            endpoint="/positions",
            taker_only=False,
            next_offset=len(current_positions),
            status="succeeded",
            run_id=run_id,
        )
        counters["checkpoints"] += 1

        closed_payload = await self._fetch_json(
            client,
            repository,
            run_id,
            "/closed-positions",
            {"user": wallet_address, "limit": page_limit},
            "data",
        )
        counters["raw_responses"] += 1
        closed_positions = [
            position
            for position in (
                normalize_closed_position(row, wallet_address=wallet_address, run_id=run_id)
                for row in first_list(closed_payload, "data")
                if isinstance(row, Mapping)
            )
            if position
        ]
        counters["closed_positions"] += repository.upsert_closed_positions(closed_positions, run_id)
        repository.update_checkpoint(
            wallet_address=wallet_address,
            endpoint="/closed-positions",
            taker_only=False,
            next_offset=len(closed_positions),
            status="succeeded",
            run_id=run_id,
        )
        counters["checkpoints"] += 1
        return counters

    async def _fetch_json(
        self,
        client: httpx.AsyncClient,
        repository: WalletDataRepository,
        run_id: str,
        endpoint: str,
        params: Mapping[str, Any],
        count_key: str,
    ) -> Any:
        data_base = str(self.settings.polymarket_data_base_url).rstrip("/")
        attempts = max(1, self.settings.wallet_backfill_retry_attempts)
        response: httpx.Response | None = None
        duration_ms = 0
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                response = await client.get(f"{data_base}{endpoint}", params=params)
            except httpx.RequestError:
                if attempt < attempts - 1:
                    await asyncio.sleep(self._retry_delay_seconds(attempt, None))
                    continue
                raise
            duration_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < attempts - 1:
                    await asyncio.sleep(self._retry_delay_seconds(attempt, response))
                    continue
            break
        if response is None:
            raise RuntimeError("request_failed_without_response")
        response.raise_for_status()
        payload = response.json()
        repository.record_raw_response(
            run_id=run_id,
            source="data",
            endpoint=endpoint,
            request_params=params,
            status_code=response.status_code,
            duration_ms=duration_ms,
            row_count=row_count(payload, count_key),
            captured_at=utc_now(),
            body=payload,
        )
        return payload

    def _retry_delay_seconds(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(float(retry_after), 30.0)
                except ValueError:
                    pass
        return min(self.settings.wallet_backfill_retry_base_seconds * (2**attempt), 30.0)


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _trade_notional(raw: Mapping[str, Any]) -> Decimal | None:
    price = parse_decimal(raw.get("price"))
    size = parse_decimal(raw.get("size"))
    if price is None or size is None:
        return None
    return price * size


async def run_wallet_backfill(settings: Settings, engine: Engine, **kwargs: Any) -> WalletBackfillResult:
    ingestion = WalletDataBackfill(settings, engine)
    return await ingestion.run(**kwargs)


def run_wallet_backfill_sync(
    settings: Settings, engine: Engine, **kwargs: Any
) -> WalletBackfillResult:
    return asyncio.run(run_wallet_backfill(settings, engine, **kwargs))
