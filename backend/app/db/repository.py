from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class MarketDataRepository:
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

    def upsert_events(self, events: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for event in events:
            self.connection.execute(
                text(
                    """
                    INSERT INTO events(
                        gamma_event_id, ticker, slug, title, description, category, active, closed,
                        archived, start_date, end_date, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :gamma_event_id, :ticker, :slug, :title, :description, :category, :active,
                        :closed, :archived, :start_date, :end_date, CAST(:raw AS jsonb), :source,
                        :run_id
                    )
                    ON CONFLICT (gamma_event_id) DO UPDATE SET
                        ticker = EXCLUDED.ticker,
                        slug = EXCLUDED.slug,
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        category = EXCLUDED.category,
                        active = EXCLUDED.active,
                        closed = EXCLUDED.closed,
                        archived = EXCLUDED.archived,
                        start_date = EXCLUDED.start_date,
                        end_date = EXCLUDED.end_date,
                        raw = EXCLUDED.raw,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**event, "run_id": run_id, "raw": _json(event["raw"])},
            )
            count += 1
        return count

    def upsert_markets(self, markets: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for market in markets:
            self.connection.execute(
                text(
                    """
                    INSERT INTO markets(
                        condition_id, gamma_market_id, gamma_event_id, slug, question, category,
                        active, closed, archived, accepting_orders, end_date, order_min_size,
                        order_price_min_tick_size, volume, liquidity, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :condition_id, :gamma_market_id, :gamma_event_id, :slug, :question, :category,
                        :active, :closed, :archived, :accepting_orders, :end_date, :order_min_size,
                        :order_price_min_tick_size, :volume, :liquidity, CAST(:raw AS jsonb), :source,
                        :run_id
                    )
                    ON CONFLICT (condition_id) DO UPDATE SET
                        gamma_market_id = EXCLUDED.gamma_market_id,
                        gamma_event_id = EXCLUDED.gamma_event_id,
                        slug = EXCLUDED.slug,
                        question = EXCLUDED.question,
                        category = EXCLUDED.category,
                        active = EXCLUDED.active,
                        closed = EXCLUDED.closed,
                        archived = EXCLUDED.archived,
                        accepting_orders = EXCLUDED.accepting_orders,
                        end_date = EXCLUDED.end_date,
                        order_min_size = EXCLUDED.order_min_size,
                        order_price_min_tick_size = EXCLUDED.order_price_min_tick_size,
                        volume = EXCLUDED.volume,
                        liquidity = EXCLUDED.liquidity,
                        raw = EXCLUDED.raw,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**market, "run_id": run_id, "raw": _json(market["raw"])},
            )
            count += 1
        return count

    def upsert_tokens(self, tokens: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for token in tokens:
            self.connection.execute(
                text(
                    """
                    INSERT INTO market_tokens(
                        token_id, condition_id, gamma_market_id, outcome_index, outcome, mapping_status,
                        mapping_error, verified_at, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :token_id, :condition_id, :gamma_market_id, :outcome_index, :outcome,
                        :mapping_status, :mapping_error, :verified_at, CAST(:raw AS jsonb), :source,
                        :run_id
                    )
                    ON CONFLICT (token_id) DO UPDATE SET
                        condition_id = EXCLUDED.condition_id,
                        gamma_market_id = EXCLUDED.gamma_market_id,
                        outcome_index = EXCLUDED.outcome_index,
                        outcome = EXCLUDED.outcome,
                        mapping_status = EXCLUDED.mapping_status,
                        mapping_error = EXCLUDED.mapping_error,
                        verified_at = EXCLUDED.verified_at,
                        raw = EXCLUDED.raw,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**token, "run_id": run_id, "raw": _json(token.get("raw", {}))},
            )
            count += 1
        return count

    def insert_liquidity_snapshots(
        self, snapshots: Iterable[Mapping[str, Any]], run_id: str
    ) -> int:
        count = 0
        for snapshot in snapshots:
            self.connection.execute(
                text(
                    """
                    INSERT INTO market_liquidity_snapshots(
                        snapshot_at, condition_id, gamma_market_id, source_endpoint, open_interest,
                        live_volume, liquidity, volume, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :snapshot_at, :condition_id, :gamma_market_id, :source_endpoint,
                        :open_interest, :live_volume, :liquidity, :volume, CAST(:raw AS jsonb),
                        :source, :run_id
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {**snapshot, "run_id": run_id, "raw": _json(snapshot["raw"])},
            )
            count += 1
        return count

    def insert_holders(self, holders: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for holder in holders:
            self.connection.execute(
                text(
                    """
                    INSERT INTO market_holders(
                        snapshot_at, condition_id, token_id, wallet_address, holder_rank, amount,
                        outcome_index, pseudonym, display_name, verified, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :snapshot_at, :condition_id, :token_id, :wallet_address, :holder_rank, :amount,
                        :outcome_index, :pseudonym, :display_name, :verified, CAST(:raw AS jsonb),
                        :source, :run_id
                    )
                    ON CONFLICT (ingestion_run_id, token_id, wallet_address) DO UPDATE SET
                        holder_rank = EXCLUDED.holder_rank,
                        amount = EXCLUDED.amount,
                        outcome_index = EXCLUDED.outcome_index,
                        pseudonym = EXCLUDED.pseudonym,
                        display_name = EXCLUDED.display_name,
                        verified = EXCLUDED.verified,
                        raw = EXCLUDED.raw,
                        updated_at = now()
                    """
                ),
                {**holder, "run_id": run_id, "raw": _json(holder["raw"])},
            )
            count += 1
        return count
