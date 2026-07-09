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
