from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import Engine

from backend.app.core.config import Settings
from backend.app.core.run_context import new_run_id
from backend.app.db.price_repository import PriceArchiveRepository

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
TEN_THOUSAND = Decimal("10000")
CLV_HORIZONS = {
    "30s": timedelta(seconds=30),
    "2m": timedelta(minutes=2),
    "10m": timedelta(minutes=10),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
}


@dataclass(frozen=True)
class PriceArchiveResult:
    run_id: str
    status: str
    counters: dict[str, int]
    started_at: datetime
    finished_at: datetime
    warnings: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, UTC)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.isdigit():
            return parse_datetime(int(candidate))
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def stable_uid(parts: list[Any]) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def row_count(payload: Any, key: str) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, Mapping) and isinstance(payload.get(key), list):
        return len(payload[key])
    return 1 if payload else 0


def normalize_price_history(
    payload: Any,
    *,
    asset_id: str,
    run_id: str,
    interval: str | None,
    fidelity: int | None,
    source_endpoint: str = "clob.prices-history",
) -> list[dict[str, Any]]:
    history = payload.get("history") if isinstance(payload, Mapping) else payload
    if not isinstance(history, list):
        return []
    rows = []
    for point in history:
        if not isinstance(point, Mapping):
            continue
        price_at = parse_datetime(
            point.get("t")
            or point.get("timestamp")
            or point.get("time")
            or point.get("price_at")
        )
        price = parse_decimal(point.get("p") or point.get("price") or point.get("value"))
        if price_at is None or price is None:
            continue
        rows.append(
            {
                "asset_id": asset_id,
                "condition_id": point.get("market") or point.get("condition_id"),
                "price_at": price_at,
                "price": price,
                "source_endpoint": source_endpoint,
                "interval": interval,
                "fidelity": fidelity,
                "raw": dict(point),
                "source": "clob",
                "ingestion_run_id": run_id,
            }
        )
    return rows


def normalize_book_level(raw: Any) -> tuple[Decimal, Decimal] | None:
    if isinstance(raw, Mapping):
        price = parse_decimal(raw.get("price") or raw.get("p"))
        size = parse_decimal(raw.get("size") or raw.get("s"))
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        price = parse_decimal(raw[0])
        size = parse_decimal(raw[1])
    else:
        return None
    if price is None or size is None:
        return None
    return price, size


def normalize_book_side(levels: Any, *, side: str) -> list[tuple[Decimal, Decimal, Any]]:
    rows = []
    if isinstance(levels, list):
        for raw_level in levels:
            normalized = normalize_book_level(raw_level)
            if normalized:
                rows.append((*normalized, raw_level))
    reverse = side == "bid"
    return sorted(rows, key=lambda row: row[0], reverse=reverse)


def normalize_orderbook(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    snapshot_at: datetime,
    depth_limit: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    asset_id = str(payload.get("asset_id") or payload.get("token_id") or "")
    condition_id = str(payload.get("market") or payload.get("condition_id") or "") or None
    bids = normalize_book_side(payload.get("bids"), side="bid")[:depth_limit]
    asks = normalize_book_side(payload.get("asks"), side="ask")[:depth_limit]
    best_bid = bids[0][0] if bids else None
    best_bid_size = bids[0][1] if bids else None
    best_ask = asks[0][0] if asks else None
    best_ask_size = asks[0][1] if asks else None
    midpoint = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
    spread_bps = spread / midpoint * TEN_THOUSAND if midpoint and midpoint > ZERO and spread is not None else None
    snapshot_uid = stable_uid(
        [
            "orderbook",
            asset_id,
            condition_id,
            payload.get("timestamp"),
            payload.get("hash"),
            snapshot_at,
            run_id,
        ]
    )
    snapshot = {
        "snapshot_uid": snapshot_uid,
        "snapshot_at": snapshot_at,
        "asset_id": asset_id,
        "condition_id": condition_id,
        "book_hash": payload.get("hash"),
        "min_order_size": parse_decimal(payload.get("min_order_size")),
        "tick_size": parse_decimal(payload.get("tick_size")),
        "raw": dict(payload),
        "source_endpoint": "clob.book",
        "source": "clob",
        "ingestion_run_id": run_id,
    }
    top = {
        "snapshot_uid": snapshot_uid,
        "snapshot_at": snapshot_at,
        "asset_id": asset_id,
        "condition_id": condition_id,
        "best_bid": best_bid,
        "best_bid_size": best_bid_size,
        "best_ask": best_ask,
        "best_ask_size": best_ask_size,
        "midpoint": midpoint,
        "spread": spread,
        "spread_bps": spread_bps,
        "top_bid_depth": sum((size for _, size, _ in bids), ZERO),
        "top_ask_depth": sum((size for _, size, _ in asks), ZERO),
        "crossed": bool(spread is not None and spread < ZERO),
        "one_sided": bool((best_bid is None) != (best_ask is None)),
        "source": "clob",
        "ingestion_run_id": run_id,
    }
    depth_rows = []
    for side, levels in [("bid", bids), ("ask", asks)]:
        cumulative_size = ZERO
        cumulative_notional = ZERO
        for index, (price, size, raw_level) in enumerate(levels, start=1):
            notional = price * size
            cumulative_size += size
            cumulative_notional += notional
            depth_rows.append(
                {
                    "snapshot_uid": snapshot_uid,
                    "snapshot_at": snapshot_at,
                    "asset_id": asset_id,
                    "condition_id": condition_id,
                    "side": side,
                    "level_index": index,
                    "price": price,
                    "size": size,
                    "notional": notional,
                    "cumulative_size": cumulative_size,
                    "cumulative_notional": cumulative_notional,
                    "raw": raw_level if isinstance(raw_level, Mapping) else {"level": raw_level},
                    "source": "clob",
                    "ingestion_run_id": run_id,
                }
            )
    return snapshot, top, depth_rows


def normalize_stream_event(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    received_at: datetime,
) -> dict[str, Any]:
    asset_id = payload.get("asset_id") or payload.get("asset") or payload.get("token_id")
    condition_id = payload.get("market") or payload.get("condition_id")
    event_at = parse_datetime(payload.get("timestamp") or payload.get("event_at") or payload.get("time"))
    event_type = str(payload.get("event_type") or payload.get("type") or "unknown")
    bids = normalize_book_side(payload.get("bids"), side="bid")
    asks = normalize_book_side(payload.get("asks"), side="ask")
    best_bid = parse_decimal(payload.get("best_bid"))
    best_ask = parse_decimal(payload.get("best_ask"))
    if best_bid is None and bids:
        best_bid = bids[0][0]
    if best_ask is None and asks:
        best_ask = asks[0][0]
    midpoint = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
    return {
        "stream_event_uid": stable_uid(
            [
                "market_stream_event",
                asset_id,
                condition_id,
                event_type,
                payload.get("timestamp"),
                payload.get("hash"),
                received_at,
                run_id,
            ]
        ),
        "received_at": received_at,
        "event_at": event_at,
        "asset_id": str(asset_id) if asset_id else None,
        "condition_id": str(condition_id) if condition_id else None,
        "event_type": event_type,
        "book_hash": payload.get("hash"),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "midpoint": midpoint,
        "spread": spread,
        "raw": dict(payload),
        "source": "clob_ws",
        "ingestion_run_id": run_id,
    }


def calculate_clv(
    *,
    side: str,
    reference_price: Decimal,
    future_price: Decimal,
) -> Decimal:
    direction = Decimal("-1") if side.strip().upper() == "SELL" else Decimal("1")
    return (future_price - reference_price) * direction


def calculate_trade_clv(
    *,
    side: str,
    trade_timestamp: datetime,
    reference_price: Decimal,
    future_prices: Mapping[str, tuple[datetime, Decimal] | None],
) -> dict[str, Decimal | None]:
    clv: dict[str, Decimal | None] = {}
    for horizon, point in future_prices.items():
        if point is None:
            clv[horizon] = None
            continue
        observed_at, future_price = point
        if observed_at < trade_timestamp:
            clv[horizon] = None
            continue
        clv[horizon] = calculate_clv(
            side=side,
            reference_price=reference_price,
            future_price=future_price,
        )
    return clv


def estimate_slippage(
    *,
    side: str,
    size: Decimal,
    levels: list[tuple[Decimal, Decimal, Any]],
) -> dict[str, Decimal | bool | None]:
    if size <= ZERO:
        return {"filled": False, "avg_price": None, "slippage": None}
    remaining = size
    filled = ZERO
    notional = ZERO
    for price, level_size, _ in levels:
        take_size = min(remaining, level_size)
        filled += take_size
        notional += take_size * price
        remaining -= take_size
        if remaining <= ZERO:
            break
    if filled < size or filled == ZERO:
        return {"filled": False, "avg_price": None, "slippage": None}
    avg_price = notional / filled
    top_price = levels[0][0]
    slippage = avg_price - top_price if side.strip().upper() == "BUY" else top_price - avg_price
    return {"filled": True, "avg_price": avg_price, "slippage": slippage}


def calculate_followability_snapshot(
    *,
    top: Mapping[str, Any],
    depth_rows: list[Mapping[str, Any]],
    requested_size: Decimal,
    max_spread_bps: Decimal,
    signal_at: datetime | None = None,
) -> dict[str, Any]:
    ask_levels = [
        (row["price"], row["size"], row.get("raw", {}))
        for row in depth_rows
        if row.get("side") == "ask" and row.get("price") is not None and row.get("size") is not None
    ]
    bid_levels = [
        (row["price"], row["size"], row.get("raw", {}))
        for row in depth_rows
        if row.get("side") == "bid" and row.get("price") is not None and row.get("size") is not None
    ]
    buy_slippage = estimate_slippage(side="BUY", size=requested_size, levels=ask_levels)
    sell_slippage = estimate_slippage(side="SELL", size=requested_size, levels=bid_levels)
    spread_bps = top.get("spread_bps")
    price_missing = top.get("best_bid") is None or top.get("best_ask") is None or top.get("midpoint") is None
    spread_too_wide = bool(spread_bps is not None and spread_bps > max_spread_bps)
    depth_insufficient = not bool(buy_slippage["filled"]) or not bool(sell_slippage["filled"])
    liquidity_score = _followability_score(
        price_missing=price_missing,
        spread_too_wide=spread_too_wide,
        depth_insufficient=depth_insufficient,
        spread_bps=spread_bps,
        max_spread_bps=max_spread_bps,
        bid_depth=top.get("top_bid_depth") or ZERO,
        ask_depth=top.get("top_ask_depth") or ZERO,
        requested_size=requested_size,
    )
    snapshot_at = top["snapshot_at"]
    signal_delay = (
        int((snapshot_at - signal_at).total_seconds())
        if signal_at is not None and isinstance(snapshot_at, datetime)
        else None
    )
    return {
        "snapshot_uid": top["snapshot_uid"],
        "snapshot_at": snapshot_at,
        "asset_id": top["asset_id"],
        "condition_id": top.get("condition_id"),
        "spread": top.get("spread"),
        "spread_bps": spread_bps,
        "top_bid_depth": top.get("top_bid_depth") or ZERO,
        "top_ask_depth": top.get("top_ask_depth") or ZERO,
        "estimated_buy_slippage": buy_slippage["slippage"],
        "estimated_sell_slippage": sell_slippage["slippage"],
        "buy_fillable": bool(buy_slippage["filled"]),
        "sell_fillable": bool(sell_slippage["filled"]),
        "spread_too_wide": spread_too_wide,
        "depth_insufficient": depth_insufficient,
        "price_missing": price_missing,
        "market_liquidity_score": liquidity_score,
        "signal_to_snapshot_delay_seconds": signal_delay,
        "notes": {
            "requested_size": requested_size,
            "max_spread_bps": max_spread_bps,
            "buy_avg_price": buy_slippage["avg_price"],
            "sell_avg_price": sell_slippage["avg_price"],
        },
        "source": "price_archive_v1",
        "ingestion_run_id": top["ingestion_run_id"],
    }


def _followability_score(
    *,
    price_missing: bool,
    spread_too_wide: bool,
    depth_insufficient: bool,
    spread_bps: Any,
    max_spread_bps: Decimal,
    bid_depth: Decimal,
    ask_depth: Decimal,
    requested_size: Decimal,
) -> Decimal:
    if price_missing or requested_size <= ZERO:
        return ZERO
    parsed_spread_bps = parse_decimal(spread_bps) or ZERO
    spread_ratio = min(parsed_spread_bps / max_spread_bps, ONE) if max_spread_bps > ZERO else ONE
    spread_score = (ONE - spread_ratio) * Decimal("50")
    bid_ratio = min(bid_depth / requested_size, ONE)
    ask_ratio = min(ask_depth / requested_size, ONE)
    depth_score = min(bid_ratio, ask_ratio) * Decimal("50")
    penalty = Decimal("20") if spread_too_wide else ZERO
    penalty += Decimal("20") if depth_insufficient else ZERO
    return max(ZERO, min(HUNDRED, spread_score + depth_score - penalty))


class PriceArchiveIngestion:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self.settings = settings
        self.engine = engine

    async def run(
        self,
        *,
        token_ids: list[str] | None = None,
        token_limit: int | None = None,
        include_price_history: bool = True,
        include_orderbook: bool = True,
        include_websocket: bool = False,
        include_clv: bool = False,
        interval: str | None = None,
        fidelity: int | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
        depth_limit: int | None = None,
        orderbook_cycles: int | None = None,
        orderbook_interval_seconds: float | None = None,
        websocket_seconds: float | None = None,
        websocket_event_limit: int | None = None,
        clv_limit: int | None = None,
        clv_reference_delay_seconds: int | None = None,
        followability_size: Decimal | None = None,
        followability_max_spread_bps: Decimal | None = None,
    ) -> PriceArchiveResult:
        run_id = new_run_id("price_archive")
        started_at = utc_now()
        token_limit = self.settings.price_archive_token_limit if token_limit is None else token_limit
        interval = self.settings.price_archive_history_interval if interval is None else interval
        fidelity = self.settings.price_archive_history_fidelity if fidelity is None else fidelity
        depth_limit = self.settings.price_archive_orderbook_depth_limit if depth_limit is None else depth_limit
        orderbook_cycles = (
            self.settings.price_archive_orderbook_cycles if orderbook_cycles is None else orderbook_cycles
        )
        orderbook_interval_seconds = (
            self.settings.price_archive_orderbook_interval_seconds
            if orderbook_interval_seconds is None
            else orderbook_interval_seconds
        )
        websocket_seconds = (
            self.settings.price_archive_websocket_seconds
            if websocket_seconds is None
            else websocket_seconds
        )
        websocket_event_limit = (
            self.settings.price_archive_websocket_event_limit
            if websocket_event_limit is None
            else websocket_event_limit
        )
        clv_limit = self.settings.price_archive_clv_limit if clv_limit is None else clv_limit
        clv_reference_delay_seconds = (
            self.settings.price_archive_clv_reference_delay_seconds
            if clv_reference_delay_seconds is None
            else clv_reference_delay_seconds
        )
        followability_size = followability_size or Decimal(self.settings.price_archive_followability_size)
        followability_max_spread_bps = followability_max_spread_bps or Decimal(
            self.settings.price_archive_followability_max_spread_bps
        )
        counters = {
            "tokens": 0,
            "price_points": 0,
            "orderbook_snapshots": 0,
            "orderbook_depth_rows": 0,
            "followability_snapshots": 0,
            "market_stream_events": 0,
            "clv_metrics": 0,
            "clv_missing_reference": 0,
            "raw_responses": 0,
            "failed_tokens": 0,
            "websocket_reconnects": 0,
        }
        warnings: list[str] = []
        params = {
            "token_ids": token_ids,
            "token_limit": token_limit,
            "include_price_history": include_price_history,
            "include_orderbook": include_orderbook,
            "include_websocket": include_websocket,
            "include_clv": include_clv,
            "interval": interval,
            "fidelity": fidelity,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "depth_limit": depth_limit,
            "orderbook_cycles": orderbook_cycles,
            "orderbook_interval_seconds": orderbook_interval_seconds,
            "websocket_seconds": websocket_seconds,
            "websocket_event_limit": websocket_event_limit,
            "clv_limit": clv_limit,
            "clv_reference_delay_seconds": clv_reference_delay_seconds,
            "followability_size": followability_size,
            "followability_max_spread_bps": followability_max_spread_bps,
        }

        with self.engine.begin() as connection:
            repository = PriceArchiveRepository(connection)
            repository.start_run(run_id, "price_archive", "polymarket", started_at, params)
            try:
                target_tokens = [str(token_id) for token_id in token_ids or [] if str(token_id).strip()]
                if not target_tokens:
                    target_tokens = repository.fetch_archive_token_ids(token_limit)
                target_tokens = target_tokens[:token_limit]
                counters["tokens"] = len(target_tokens)
                if not target_tokens:
                    warnings.append("no_target_tokens_found")

                async with httpx.AsyncClient(timeout=self.settings.api_probe_timeout_seconds) as client:
                    for token_id in target_tokens:
                        if include_price_history:
                            inserted = await self._archive_price_history(
                                client,
                                repository,
                                run_id,
                                token_id,
                                interval,
                                fidelity,
                                start_ts,
                                end_ts,
                            )
                            counters["price_points"] += inserted["price_points"]
                            counters["raw_responses"] += inserted["raw_responses"]
                            counters["failed_tokens"] += inserted["failed_tokens"]
                    if include_orderbook and target_tokens:
                        for cycle_index in range(max(orderbook_cycles, 0)):
                            if cycle_index > 0:
                                await asyncio.sleep(max(orderbook_interval_seconds, 0))
                            for token_id in target_tokens:
                                inserted = await self._archive_orderbook(
                                    client,
                                    repository,
                                    run_id,
                                    token_id,
                                    depth_limit,
                                    followability_size,
                                    followability_max_spread_bps,
                                )
                                counters["orderbook_snapshots"] += inserted["orderbook_snapshots"]
                                counters["orderbook_depth_rows"] += inserted["orderbook_depth_rows"]
                                counters["followability_snapshots"] += inserted["followability_snapshots"]
                                counters["raw_responses"] += inserted["raw_responses"]
                                counters["failed_tokens"] += inserted["failed_tokens"]

                if include_clv:
                    inserted = self._materialize_clv_metrics(
                        repository,
                        run_id,
                        clv_limit,
                        clv_reference_delay_seconds,
                    )
                    counters["clv_metrics"] += inserted["clv_metrics"]
                    counters["clv_missing_reference"] += inserted["clv_missing_reference"]

                if include_websocket and target_tokens:
                    stream_counters = await self._archive_websocket(
                        repository,
                        run_id,
                        target_tokens,
                        websocket_seconds,
                        websocket_event_limit,
                    )
                    for key, value in stream_counters.items():
                        counters[key] += value

                finished_at = utc_now()
                repository.finish_run(run_id, "succeeded", finished_at, counters)
                return PriceArchiveResult(run_id, "succeeded", counters, started_at, finished_at, warnings)
            except Exception as exc:
                finished_at = utc_now()
                repository.finish_run(run_id, "failed", finished_at, counters, str(exc))
                raise

    async def _archive_price_history(
        self,
        client: httpx.AsyncClient,
        repository: PriceArchiveRepository,
        run_id: str,
        token_id: str,
        interval: str | None,
        fidelity: int | None,
        start_ts: int | None,
        end_ts: int | None,
    ) -> dict[str, int]:
        params: dict[str, Any] = {"market": token_id}
        if interval:
            params["interval"] = interval
        if fidelity is not None:
            params["fidelity"] = fidelity
        if start_ts is not None:
            params["startTs"] = start_ts
        if end_ts is not None:
            params["endTs"] = end_ts
        payload, status_code, duration_ms = await self._fetch_clob(client, "/prices-history", params)
        repository.record_raw_response(
            run_id=run_id,
            source="clob",
            endpoint="/prices-history",
            request_params=params,
            status_code=status_code,
            duration_ms=duration_ms,
            row_count=row_count(payload, "history"),
            captured_at=utc_now(),
            body=payload,
        )
        if status_code >= 400:
            return {"price_points": 0, "raw_responses": 1, "failed_tokens": 1}
        rows = normalize_price_history(
            payload,
            asset_id=token_id,
            run_id=run_id,
            interval=interval,
            fidelity=fidelity,
        )
        return {
            "price_points": repository.insert_price_points(rows, run_id),
            "raw_responses": 1,
            "failed_tokens": 0,
        }

    async def _archive_orderbook(
        self,
        client: httpx.AsyncClient,
        repository: PriceArchiveRepository,
        run_id: str,
        token_id: str,
        depth_limit: int,
        followability_size: Decimal,
        followability_max_spread_bps: Decimal,
    ) -> dict[str, int]:
        params = {"token_id": token_id}
        payload, status_code, duration_ms = await self._fetch_clob(client, "/book", params)
        repository.record_raw_response(
            run_id=run_id,
            source="clob",
            endpoint="/book",
            request_params=params,
            status_code=status_code,
            duration_ms=duration_ms,
            row_count=row_count(payload, "bids"),
            captured_at=utc_now(),
            body=payload,
        )
        if status_code >= 400 or not isinstance(payload, Mapping):
            return {
                "orderbook_snapshots": 0,
                "orderbook_depth_rows": 0,
                "followability_snapshots": 0,
                "raw_responses": 1,
                "failed_tokens": 1,
            }
        snapshot, top, depth_rows = normalize_orderbook(
            payload,
            run_id=run_id,
            snapshot_at=utc_now(),
            depth_limit=depth_limit,
        )
        repository.upsert_orderbook_snapshot(snapshot, top, depth_rows, run_id)
        followability = calculate_followability_snapshot(
            top=top,
            depth_rows=depth_rows,
            requested_size=followability_size,
            max_spread_bps=followability_max_spread_bps,
        )
        repository.upsert_followability_snapshot(followability, run_id)
        return {
            "orderbook_snapshots": 1,
            "orderbook_depth_rows": len(depth_rows),
            "followability_snapshots": 1,
            "raw_responses": 1,
            "failed_tokens": 0,
        }

    def _materialize_clv_metrics(
        self,
        repository: PriceArchiveRepository,
        run_id: str,
        limit: int,
        reference_delay_seconds: int,
    ) -> dict[str, int]:
        calculated_at = utc_now()
        rows = []
        missing_reference = 0
        for trade in repository.fetch_trades_for_clv(limit):
            metric = self._build_trade_clv_metric(
                repository=repository,
                trade=trade,
                run_id=run_id,
                calculated_at=calculated_at,
                reference_delay_seconds=reference_delay_seconds,
            )
            if metric.get("missing_reason"):
                missing_reference += 1
            rows.append(metric)
        return {
            "clv_metrics": repository.upsert_trade_clv_metrics(rows, run_id),
            "clv_missing_reference": missing_reference,
        }

    def _build_trade_clv_metric(
        self,
        *,
        repository: PriceArchiveRepository,
        trade: Mapping[str, Any],
        run_id: str,
        calculated_at: datetime,
        reference_delay_seconds: int,
    ) -> dict[str, Any]:
        token_id = str(trade["token_id"])
        trade_timestamp = trade["trade_timestamp"]
        reference_target = trade_timestamp + timedelta(seconds=reference_delay_seconds)
        reference = repository.fetch_market_price_after(
            token_id=token_id,
            target_at=reference_target,
            prefer_midpoint=True,
        )
        future_points: dict[str, tuple[datetime, Decimal] | None] = {}
        future_prices: dict[str, Decimal | None] = {}
        for label, horizon in CLV_HORIZONS.items():
            point = repository.fetch_market_price_after(
                token_id=token_id,
                target_at=trade_timestamp + horizon,
                prefer_midpoint=True,
            )
            if point and point.get("price") is not None and point.get("observed_at") is not None:
                price = parse_decimal(point["price"])
                future_points[label] = (point["observed_at"], price) if price is not None else None
                future_prices[label] = price
            else:
                future_points[label] = None
                future_prices[label] = None
        reference_price = parse_decimal(reference.get("price")) if reference else None
        clv_values = (
            calculate_trade_clv(
                side=str(trade["side"]),
                trade_timestamp=trade_timestamp,
                reference_price=reference_price,
                future_prices=future_points,
            )
            if reference_price is not None
            else {label: None for label in CLV_HORIZONS}
        )
        reference_at = reference.get("observed_at") if reference else None
        signal_delay = (
            int((reference_at - trade_timestamp).total_seconds())
            if isinstance(reference_at, datetime)
            else None
        )
        missing_reason = None
        if reference_price is None:
            missing_reason = "missing_reference_price"
        elif all(value is None for value in clv_values.values()):
            missing_reason = "missing_future_prices"
        return {
            "trade_uid": trade["trade_uid"],
            "wallet_address": trade["wallet_address"],
            "condition_id": trade.get("condition_id"),
            "token_id": token_id,
            "side": trade.get("side"),
            "trade_timestamp": trade_timestamp,
            "trade_price": trade.get("price"),
            "reference_price": reference_price,
            "reference_source": reference.get("source") if reference else None,
            "reference_at": reference_at,
            "signal_to_reference_delay_seconds": signal_delay,
            "clv_30s": clv_values["30s"],
            "clv_2m": clv_values["2m"],
            "clv_10m": clv_values["10m"],
            "clv_1h": clv_values["1h"],
            "clv_24h": clv_values["24h"],
            "future_price_30s": future_prices["30s"],
            "future_price_2m": future_prices["2m"],
            "future_price_10m": future_prices["10m"],
            "future_price_1h": future_prices["1h"],
            "future_price_24h": future_prices["24h"],
            "missing_reason": missing_reason,
            "calculated_at": calculated_at,
            "source": "price_archive_clv_v1",
            "ingestion_run_id": run_id,
        }

    async def _fetch_clob(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        params: Mapping[str, Any],
    ) -> tuple[Any, int, int]:
        started = time.perf_counter()
        url = f"{str(self.settings.polymarket_clob_base_url).rstrip('/')}{endpoint}"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await client.get(url, params=params)
                duration_ms = int((time.perf_counter() - started) * 1000)
                try:
                    payload = response.json()
                except ValueError:
                    payload = {"body": response.text[:1000]}
                return payload, response.status_code, duration_ms
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "error": type(last_error).__name__ if last_error else "HTTPError",
            "message": str(last_error) if last_error else "unknown http error",
        }, 0, duration_ms

    async def _archive_websocket(
        self,
        repository: PriceArchiveRepository,
        run_id: str,
        token_ids: list[str],
        websocket_seconds: float,
        websocket_event_limit: int,
    ) -> dict[str, int]:
        counters = {"market_stream_events": 0, "websocket_reconnects": 0}
        try:
            import websockets
        except ImportError:
            return counters

        deadline = utc_now() + timedelta(seconds=websocket_seconds)
        url = f"{str(self.settings.polymarket_ws_base_url).rstrip('/')}/market"
        while utc_now() < deadline and counters["market_stream_events"] < websocket_event_limit:
            try:
                async with websockets.connect(
                    url,
                    open_timeout=self.settings.api_probe_timeout_seconds,
                    close_timeout=2,
                ) as websocket:
                    await websocket.send(json.dumps({"assets_ids": token_ids, "type": "market"}))
                    while utc_now() < deadline and counters["market_stream_events"] < websocket_event_limit:
                        timeout = max((deadline - utc_now()).total_seconds(), 0.1)
                        message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                        received_at = utc_now()
                        payload = json.loads(message) if str(message).startswith(("{", "[")) else message
                        payloads = payload if isinstance(payload, list) else [payload]
                        rows = [
                            normalize_stream_event(item, run_id=run_id, received_at=received_at)
                            for item in payloads
                            if isinstance(item, Mapping)
                        ]
                        counters["market_stream_events"] += repository.insert_market_stream_events(rows, run_id)
            except TimeoutError:
                break
            except Exception:
                counters["websocket_reconnects"] += 1
                await asyncio.sleep(1)
        return counters


async def run_price_archive(settings: Settings, engine: Engine, **kwargs: Any) -> PriceArchiveResult:
    ingestion = PriceArchiveIngestion(settings, engine)
    return await ingestion.run(**kwargs)


def run_price_archive_sync(settings: Settings, engine: Engine, **kwargs: Any) -> PriceArchiveResult:
    return asyncio.run(run_price_archive(settings, engine, **kwargs))
