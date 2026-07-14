from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class PriceArchiveRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def start_run(
        self,
        run_id: str,
        job_name: str,
        source: str,
        started_at: datetime,
        params: Mapping[str, Any],
    ) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO ingestion_runs(run_id, job_name, source, status, started_at, params)
                VALUES (:run_id, :job_name, :source, 'running', :started_at, CAST(:params AS jsonb))
                ON CONFLICT (run_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    started_at = EXCLUDED.started_at,
                    params = EXCLUDED.params,
                    updated_at = now()
                """
            ),
            {
                "run_id": run_id,
                "job_name": job_name,
                "source": source,
                "started_at": started_at,
                "params": _json(params),
            },
        )

    def finish_run(
        self,
        run_id: str,
        status: str,
        finished_at: datetime,
        counters: Mapping[str, Any],
        error: str | None = None,
    ) -> None:
        self.connection.execute(
            text(
                """
                UPDATE ingestion_runs
                SET status = :status,
                    finished_at = :finished_at,
                    counters = CAST(:counters AS jsonb),
                    error = :error,
                    updated_at = now()
                WHERE run_id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "status": status,
                "finished_at": finished_at,
                "counters": _json(counters),
                "error": error,
            },
        )

    def record_raw_response(
        self,
        *,
        run_id: str,
        source: str,
        endpoint: str,
        request_params: Mapping[str, Any],
        status_code: int,
        duration_ms: int,
        row_count: int,
        captured_at: datetime,
        body: Any,
    ) -> str:
        body_json = _json(body)
        response_hash = hashlib.sha256(body_json.encode("utf-8")).hexdigest()
        self.connection.execute(
            text(
                """
                INSERT INTO raw_api_responses(
                    source, endpoint, request_params, status_code, duration_ms, row_count,
                    response_hash, response_body, captured_at, ingestion_run_id
                )
                VALUES (
                    :source, :endpoint, CAST(:request_params AS jsonb), :status_code, :duration_ms,
                    :row_count, :response_hash, CAST(:response_body AS jsonb), :captured_at, :run_id
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "run_id": run_id,
                "source": source,
                "endpoint": endpoint,
                "request_params": _json(request_params),
                "status_code": status_code,
                "duration_ms": duration_ms,
                "row_count": row_count,
                "response_hash": response_hash,
                "response_body": body_json,
                "captured_at": captured_at,
            },
        )
        return response_hash

    def fetch_archive_token_ids(self, limit: int) -> list[str]:
        result = self.connection.execute(
            text(
                """
                SELECT mt.token_id
                FROM market_tokens mt
                JOIN markets m ON m.condition_id = mt.condition_id
                WHERE mt.mapping_status IN ('mapped', 'verified')
                    AND COALESCE(m.active, false) = true
                    AND COALESCE(m.closed, false) = false
                ORDER BY COALESCE(m.volume, 0) DESC, mt.updated_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [str(row.token_id) for row in result]

    def insert_price_points(self, rows: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                text(
                    """
                    INSERT INTO price_points(
                        asset_id, condition_id, price_at, price, source_endpoint, interval,
                        fidelity, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :asset_id, :condition_id, :price_at, :price, :source_endpoint,
                        :interval, :fidelity, CAST(:raw AS jsonb), :source, :run_id
                    )
                    ON CONFLICT (asset_id, price_at, source_endpoint, COALESCE(interval, ''), COALESCE(fidelity, -1))
                    DO UPDATE SET
                        condition_id = EXCLUDED.condition_id,
                        price = EXCLUDED.price,
                        raw = EXCLUDED.raw,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**row, "run_id": run_id, "raw": _json(row.get("raw", {}))},
            )
            count += 1
        return count

    def upsert_orderbook_snapshot(
        self,
        snapshot: Mapping[str, Any],
        top: Mapping[str, Any],
        depth_rows: Iterable[Mapping[str, Any]],
        run_id: str,
    ) -> int:
        self.connection.execute(
            text(
                """
                INSERT INTO orderbook_snapshots(
                    snapshot_uid, snapshot_at, asset_id, condition_id, book_hash,
                    min_order_size, tick_size, raw, source_endpoint, source, ingestion_run_id
                )
                VALUES (
                    :snapshot_uid, :snapshot_at, :asset_id, :condition_id, :book_hash,
                    :min_order_size, :tick_size, CAST(:raw AS jsonb), :source_endpoint,
                    :source, :run_id
                )
                ON CONFLICT (snapshot_uid) DO UPDATE SET
                    raw = EXCLUDED.raw,
                    source = EXCLUDED.source,
                    ingestion_run_id = EXCLUDED.ingestion_run_id,
                    updated_at = now()
                """
            ),
            {**snapshot, "run_id": run_id, "raw": _json(snapshot.get("raw", {}))},
        )
        self.connection.execute(
            text(
                """
                INSERT INTO orderbook_top(
                    snapshot_uid, snapshot_at, asset_id, condition_id, best_bid, best_bid_size,
                    best_ask, best_ask_size, midpoint, spread, spread_bps, top_bid_depth,
                    top_ask_depth, crossed, one_sided, source, ingestion_run_id
                )
                VALUES (
                    :snapshot_uid, :snapshot_at, :asset_id, :condition_id, :best_bid,
                    :best_bid_size, :best_ask, :best_ask_size, :midpoint, :spread,
                    :spread_bps, :top_bid_depth, :top_ask_depth, :crossed, :one_sided,
                    :source, :run_id
                )
                ON CONFLICT (snapshot_uid) DO UPDATE SET
                    best_bid = EXCLUDED.best_bid,
                    best_bid_size = EXCLUDED.best_bid_size,
                    best_ask = EXCLUDED.best_ask,
                    best_ask_size = EXCLUDED.best_ask_size,
                    midpoint = EXCLUDED.midpoint,
                    spread = EXCLUDED.spread,
                    spread_bps = EXCLUDED.spread_bps,
                    top_bid_depth = EXCLUDED.top_bid_depth,
                    top_ask_depth = EXCLUDED.top_ask_depth,
                    crossed = EXCLUDED.crossed,
                    one_sided = EXCLUDED.one_sided,
                    source = EXCLUDED.source,
                    ingestion_run_id = EXCLUDED.ingestion_run_id,
                    updated_at = now()
                """
            ),
            {**top, "run_id": run_id},
        )
        count = 1
        for row in depth_rows:
            self.connection.execute(
                text(
                    """
                    INSERT INTO orderbook_depth_snapshots(
                        snapshot_uid, snapshot_at, asset_id, condition_id, side, level_index,
                        price, size, notional, cumulative_size, cumulative_notional, raw,
                        source, ingestion_run_id
                    )
                    VALUES (
                        :snapshot_uid, :snapshot_at, :asset_id, :condition_id, :side,
                        :level_index, :price, :size, :notional, :cumulative_size,
                        :cumulative_notional, CAST(:raw AS jsonb), :source, :run_id
                    )
                    ON CONFLICT (snapshot_uid, side, level_index) DO UPDATE SET
                        price = EXCLUDED.price,
                        size = EXCLUDED.size,
                        notional = EXCLUDED.notional,
                        cumulative_size = EXCLUDED.cumulative_size,
                        cumulative_notional = EXCLUDED.cumulative_notional,
                        raw = EXCLUDED.raw,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**row, "run_id": run_id, "raw": _json(row.get("raw", {}))},
            )
            count += 1
        return count

    def upsert_followability_snapshot(self, row: Mapping[str, Any], run_id: str) -> int:
        self.connection.execute(
            text(
                """
                INSERT INTO market_followability_snapshots(
                    snapshot_uid, snapshot_at, asset_id, condition_id, spread, spread_bps,
                    top_bid_depth, top_ask_depth, estimated_buy_slippage,
                    estimated_sell_slippage, buy_fillable, sell_fillable, spread_too_wide,
                    depth_insufficient, price_missing, market_liquidity_score,
                    signal_to_snapshot_delay_seconds, notes, source, ingestion_run_id
                )
                VALUES (
                    :snapshot_uid, :snapshot_at, :asset_id, :condition_id, :spread, :spread_bps,
                    :top_bid_depth, :top_ask_depth, :estimated_buy_slippage,
                    :estimated_sell_slippage, :buy_fillable, :sell_fillable,
                    :spread_too_wide, :depth_insufficient, :price_missing,
                    :market_liquidity_score, :signal_to_snapshot_delay_seconds,
                    CAST(:notes AS jsonb), :source, :run_id
                )
                ON CONFLICT (snapshot_uid) DO UPDATE SET
                    spread = EXCLUDED.spread,
                    spread_bps = EXCLUDED.spread_bps,
                    top_bid_depth = EXCLUDED.top_bid_depth,
                    top_ask_depth = EXCLUDED.top_ask_depth,
                    estimated_buy_slippage = EXCLUDED.estimated_buy_slippage,
                    estimated_sell_slippage = EXCLUDED.estimated_sell_slippage,
                    buy_fillable = EXCLUDED.buy_fillable,
                    sell_fillable = EXCLUDED.sell_fillable,
                    spread_too_wide = EXCLUDED.spread_too_wide,
                    depth_insufficient = EXCLUDED.depth_insufficient,
                    price_missing = EXCLUDED.price_missing,
                    market_liquidity_score = EXCLUDED.market_liquidity_score,
                    signal_to_snapshot_delay_seconds = EXCLUDED.signal_to_snapshot_delay_seconds,
                    notes = EXCLUDED.notes,
                    source = EXCLUDED.source,
                    ingestion_run_id = EXCLUDED.ingestion_run_id,
                    updated_at = now()
                """
            ),
            {**row, "run_id": run_id, "notes": _json(row.get("notes", {}))},
        )
        return 1

    def insert_market_stream_events(self, rows: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                text(
                    """
                    INSERT INTO market_stream_events(
                        stream_event_uid, received_at, event_at, asset_id, condition_id,
                        event_type, book_hash, best_bid, best_ask, midpoint, spread, raw,
                        source, ingestion_run_id
                    )
                    VALUES (
                        :stream_event_uid, :received_at, :event_at, :asset_id, :condition_id,
                        :event_type, :book_hash, :best_bid, :best_ask, :midpoint, :spread,
                        CAST(:raw AS jsonb), :source, :run_id
                    )
                    ON CONFLICT (stream_event_uid) DO UPDATE SET
                        raw = EXCLUDED.raw,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**row, "run_id": run_id, "raw": _json(row.get("raw", {}))},
            )
            count += 1
        return count

    def fetch_trades_for_clv(
        self,
        limit: int,
        wallet_addresses: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        restrict_wallets = wallet_addresses is not None
        result = self.connection.execute(
            text(
                """
                SELECT
                    t.trade_uid,
                    t.wallet_address,
                    t.condition_id,
                    t.token_id,
                    t.side,
                    t.price,
                    t.trade_timestamp
                FROM trades t
                LEFT JOIN trade_clv_metrics existing
                    ON existing.trade_uid = t.trade_uid
                WHERE t.token_id IS NOT NULL
                    AND t.trade_timestamp IS NOT NULL
                    AND t.price IS NOT NULL
                    AND t.side IS NOT NULL
                    AND (
                        NOT :restrict_wallets
                        OR t.wallet_address = ANY(:wallet_addresses)
                    )
                    AND (
                        existing.trade_uid IS NULL
                        OR (existing.clv_30s IS NULL
                            AND t.trade_timestamp <= now() - interval '30 seconds')
                        OR (existing.clv_2m IS NULL
                            AND t.trade_timestamp <= now() - interval '2 minutes')
                        OR (existing.clv_10m IS NULL
                            AND t.trade_timestamp <= now() - interval '10 minutes')
                        OR (existing.clv_1h IS NULL
                            AND t.trade_timestamp <= now() - interval '1 hour')
                        OR (existing.clv_24h IS NULL
                            AND t.trade_timestamp <= now() - interval '24 hours')
                    )
                ORDER BY (existing.trade_uid IS NULL) DESC, t.trade_timestamp DESC
                LIMIT :limit
                """
            ),
            {
                "limit": limit,
                "restrict_wallets": restrict_wallets,
                "wallet_addresses": wallet_addresses or [],
            },
        )
        return [dict(row._mapping) for row in result]

    def fetch_market_price_after(
        self,
        *,
        token_id: str,
        target_at: datetime,
        prefer_midpoint: bool = True,
    ) -> dict[str, Any] | None:
        if prefer_midpoint:
            midpoint = self.connection.execute(
                text(
                    """
                    SELECT
                        snapshot_at AS observed_at,
                        midpoint AS price,
                        'orderbook_midpoint' AS source
                    FROM orderbook_top
                    WHERE asset_id = :token_id
                        AND snapshot_at >= :target_at
                        AND midpoint IS NOT NULL
                    ORDER BY snapshot_at
                    LIMIT 1
                    """
                ),
                {"token_id": token_id, "target_at": target_at},
            ).one_or_none()
            if midpoint:
                return dict(midpoint._mapping)

        price_point = self.connection.execute(
            text(
                """
                SELECT
                    price_at AS observed_at,
                    price,
                    'price_history' AS source
                FROM price_points
                WHERE asset_id = :token_id
                    AND price_at >= :target_at
                ORDER BY price_at
                LIMIT 1
                """
            ),
            {"token_id": token_id, "target_at": target_at},
        ).one_or_none()
        return dict(price_point._mapping) if price_point else None

    def upsert_trade_clv_metrics(self, rows: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                text(
                    """
                    INSERT INTO trade_clv_metrics(
                        trade_uid, wallet_address, condition_id, token_id, side, trade_timestamp,
                        trade_price, reference_price, reference_source, reference_at,
                        signal_to_reference_delay_seconds, clv_30s, clv_2m, clv_10m,
                        clv_1h, clv_24h, future_price_30s, future_price_2m,
                        future_price_10m, future_price_1h, future_price_24h,
                        missing_reason, calculated_at, source, ingestion_run_id
                    )
                    VALUES (
                        :trade_uid, :wallet_address, :condition_id, :token_id, :side,
                        :trade_timestamp, :trade_price, :reference_price, :reference_source,
                        :reference_at, :signal_to_reference_delay_seconds, :clv_30s,
                        :clv_2m, :clv_10m, :clv_1h, :clv_24h, :future_price_30s,
                        :future_price_2m, :future_price_10m, :future_price_1h,
                        :future_price_24h, :missing_reason, :calculated_at, :source, :run_id
                    )
                    ON CONFLICT (trade_uid) DO UPDATE SET
                        reference_price = EXCLUDED.reference_price,
                        reference_source = EXCLUDED.reference_source,
                        reference_at = EXCLUDED.reference_at,
                        signal_to_reference_delay_seconds = EXCLUDED.signal_to_reference_delay_seconds,
                        clv_30s = EXCLUDED.clv_30s,
                        clv_2m = EXCLUDED.clv_2m,
                        clv_10m = EXCLUDED.clv_10m,
                        clv_1h = EXCLUDED.clv_1h,
                        clv_24h = EXCLUDED.clv_24h,
                        future_price_30s = EXCLUDED.future_price_30s,
                        future_price_2m = EXCLUDED.future_price_2m,
                        future_price_10m = EXCLUDED.future_price_10m,
                        future_price_1h = EXCLUDED.future_price_1h,
                        future_price_24h = EXCLUDED.future_price_24h,
                        missing_reason = EXCLUDED.missing_reason,
                        calculated_at = EXCLUDED.calculated_at,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**row, "run_id": run_id},
            )
            count += 1
        return count
