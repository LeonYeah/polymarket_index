from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class WalletDataRepository:
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

    def upsert_wallets(self, wallets: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for wallet in wallets:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallets(
                        wallet_address, first_seen_at, last_seen_at, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :wallet_address, :first_seen_at, :last_seen_at, CAST(:raw AS jsonb),
                        :source, :run_id
                    )
                    ON CONFLICT (wallet_address) DO UPDATE SET
                        first_seen_at = LEAST(
                            COALESCE(wallets.first_seen_at, EXCLUDED.first_seen_at),
                            COALESCE(EXCLUDED.first_seen_at, wallets.first_seen_at)
                        ),
                        last_seen_at = GREATEST(
                            COALESCE(wallets.last_seen_at, EXCLUDED.last_seen_at),
                            COALESCE(EXCLUDED.last_seen_at, wallets.last_seen_at)
                        ),
                        raw = wallets.raw || EXCLUDED.raw,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {
                    **wallet,
                    "run_id": run_id,
                    "raw": _json(wallet.get("raw", {})),
                },
            )
            count += 1
        return count

    def upsert_candidates(self, candidates: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for candidate in candidates:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_candidates(
                        wallet_address, seed_source, seed_ref, discovered_at, rank, score, raw,
                        source, ingestion_run_id
                    )
                    VALUES (
                        :wallet_address, :seed_source, :seed_ref, :discovered_at, :rank, :score,
                        CAST(:raw AS jsonb), :source, :run_id
                    )
                    ON CONFLICT (wallet_address, seed_source, COALESCE(seed_ref, '')) DO UPDATE SET
                        discovered_at = LEAST(wallet_candidates.discovered_at, EXCLUDED.discovered_at),
                        rank = EXCLUDED.rank,
                        score = EXCLUDED.score,
                        raw = wallet_candidates.raw || EXCLUDED.raw,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {
                    **candidate,
                    "run_id": run_id,
                    "raw": _json(candidate.get("raw", {})),
                },
            )
            count += 1
        return count

    def fetch_holder_candidates(self, limit: int) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    wallet_address,
                    max(snapshot_at) AS last_seen_at,
                    count(DISTINCT token_id) AS token_count,
                    max(condition_id) AS seed_ref
                FROM market_holders
                GROUP BY wallet_address
                ORDER BY token_count DESC, last_seen_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [dict(row._mapping) for row in result]

    def fetch_candidate_wallets(self, limit: int) -> list[str]:
        result = self.connection.execute(
            text(
                """
                WITH candidate_profile AS (
                    SELECT
                        wallet_address,
                        bool_or(seed_source = 'holder') AS has_holder_seed,
                        bool_or(seed_source IN ('leaderboard', 'active_trader')) AS has_activity_seed
                    FROM wallet_candidates
                    GROUP BY wallet_address
                )
                SELECT w.wallet_address
                FROM wallets w
                LEFT JOIN candidate_profile cp
                    ON cp.wallet_address = w.wallet_address
                LEFT JOIN wallet_backfill_checkpoints trades_checkpoint
                    ON trades_checkpoint.wallet_address = w.wallet_address
                    AND trades_checkpoint.endpoint = '/trades'
                    AND trades_checkpoint.taker_only = false
                ORDER BY
                    CASE
                        WHEN trades_checkpoint.wallet_address IS NULL THEN 0
                        WHEN trades_checkpoint.status = 'running' THEN 1
                        WHEN trades_checkpoint.status = 'exhausted' THEN 2
                        ELSE 1
                    END,
                    CASE
                        WHEN cp.has_holder_seed AND NOT cp.has_activity_seed THEN 0
                        ELSE 1
                    END,
                    w.last_seen_at DESC NULLS LAST,
                    w.updated_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [str(row.wallet_address) for row in result]

    def count_candidate_wallets(self) -> int:
        result = self.connection.execute(
            text("SELECT count(DISTINCT wallet_address) AS count FROM wallet_candidates")
        ).one()
        return int(result.count)

    def count_backfilled_wallets(self) -> int:
        result = self.connection.execute(
            text(
                """
                SELECT count(DISTINCT wallet_address) AS count
                FROM wallet_backfill_checkpoints
                WHERE endpoint IN ('/trades', '/positions', '/closed-positions')
                GROUP BY wallet_address
                HAVING count(DISTINCT endpoint) = 3
                """
            )
        ).all()
        return len(result)

    def count_trade_exhausted_wallets(self) -> int:
        result = self.connection.execute(
            text(
                """
                SELECT count(DISTINCT wallet_address) AS count
                FROM wallet_backfill_checkpoints
                WHERE endpoint = '/trades'
                    AND status = 'exhausted'
                """
            )
        ).one()
        return int(result.count)

    def get_checkpoint_offset(self, wallet_address: str, endpoint: str, taker_only: bool) -> int:
        result = self.connection.execute(
            text(
                """
                SELECT next_offset
                FROM wallet_backfill_checkpoints
                WHERE wallet_address = :wallet_address
                    AND endpoint = :endpoint
                    AND taker_only = :taker_only
                """
            ),
            {
                "wallet_address": wallet_address,
                "endpoint": endpoint,
                "taker_only": taker_only,
            },
        ).one_or_none()
        return int(result.next_offset) if result else 0

    def update_checkpoint(
        self,
        *,
        wallet_address: str,
        endpoint: str,
        taker_only: bool,
        next_offset: int,
        status: str,
        run_id: str,
        last_error: str | None = None,
    ) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO wallet_backfill_checkpoints(
                    wallet_address, endpoint, taker_only, next_offset, status, last_error,
                    ingestion_run_id
                )
                VALUES (
                    :wallet_address, :endpoint, :taker_only, :next_offset, :status, :last_error,
                    :run_id
                )
                ON CONFLICT (wallet_address, endpoint, taker_only) DO UPDATE SET
                    next_offset = EXCLUDED.next_offset,
                    status = EXCLUDED.status,
                    last_error = EXCLUDED.last_error,
                    ingestion_run_id = EXCLUDED.ingestion_run_id,
                    updated_at = now()
                """
            ),
            {
                "wallet_address": wallet_address,
                "endpoint": endpoint,
                "taker_only": taker_only,
                "next_offset": next_offset,
                "status": status,
                "last_error": last_error,
                "run_id": run_id,
            },
        )

    def upsert_trades(self, trades: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for trade in trades:
            self.connection.execute(
                text(
                    """
                    INSERT INTO trades(
                        trade_uid, api_trade_id, wallet_address, proxy_wallet, condition_id,
                        token_id, side, price, size, notional, trade_timestamp, transaction_hash,
                        taker_only, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :trade_uid, :api_trade_id, :wallet_address, :proxy_wallet, :condition_id,
                        :token_id, :side, :price, :size, :notional, :trade_timestamp,
                        :transaction_hash, :taker_only, CAST(:raw AS jsonb), :source, :run_id
                    )
                    ON CONFLICT (trade_uid) DO UPDATE SET
                        api_trade_id = EXCLUDED.api_trade_id,
                        price = EXCLUDED.price,
                        size = EXCLUDED.size,
                        notional = EXCLUDED.notional,
                        raw = EXCLUDED.raw,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**trade, "run_id": run_id, "raw": _json(trade["raw"])},
            )
            count += 1
        return count

    def upsert_current_positions(
        self, positions: Iterable[Mapping[str, Any]], run_id: str
    ) -> int:
        count = 0
        for position in positions:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_positions_current(
                        position_uid, wallet_address, condition_id, token_id, outcome, size,
                        avg_price, initial_value, current_value, cash_pnl, realized_pnl, cur_price,
                        redeemable, mergeable, title, slug, event_slug, end_date, snapshot_at,
                        raw, source, ingestion_run_id
                    )
                    VALUES (
                        :position_uid, :wallet_address, :condition_id, :token_id, :outcome,
                        :size, :avg_price, :initial_value, :current_value, :cash_pnl,
                        :realized_pnl, :cur_price, :redeemable, :mergeable, :title, :slug,
                        :event_slug, :end_date, :snapshot_at, CAST(:raw AS jsonb), :source, :run_id
                    )
                    ON CONFLICT (position_uid) DO UPDATE SET
                        size = EXCLUDED.size,
                        avg_price = EXCLUDED.avg_price,
                        initial_value = EXCLUDED.initial_value,
                        current_value = EXCLUDED.current_value,
                        cash_pnl = EXCLUDED.cash_pnl,
                        realized_pnl = EXCLUDED.realized_pnl,
                        cur_price = EXCLUDED.cur_price,
                        redeemable = EXCLUDED.redeemable,
                        mergeable = EXCLUDED.mergeable,
                        snapshot_at = EXCLUDED.snapshot_at,
                        raw = EXCLUDED.raw,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**position, "run_id": run_id, "raw": _json(position["raw"])},
            )
            count += 1
        return count

    def upsert_closed_positions(
        self, positions: Iterable[Mapping[str, Any]], run_id: str
    ) -> int:
        count = 0
        for position in positions:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_positions_closed(
                        position_uid, wallet_address, condition_id, token_id, outcome, avg_price,
                        total_bought, realized_pnl, cur_price, title, slug, event_slug, end_date,
                        closed_at, raw, source, ingestion_run_id
                    )
                    VALUES (
                        :position_uid, :wallet_address, :condition_id, :token_id, :outcome,
                        :avg_price, :total_bought, :realized_pnl, :cur_price, :title, :slug,
                        :event_slug, :end_date, :closed_at, CAST(:raw AS jsonb), :source, :run_id
                    )
                    ON CONFLICT (position_uid) DO UPDATE SET
                        avg_price = EXCLUDED.avg_price,
                        total_bought = EXCLUDED.total_bought,
                        realized_pnl = EXCLUDED.realized_pnl,
                        cur_price = EXCLUDED.cur_price,
                        raw = EXCLUDED.raw,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**position, "run_id": run_id, "raw": _json(position["raw"])},
            )
            count += 1
        return count

    def refresh_wallet_activity(self, wallet_addresses: Iterable[str], run_id: str) -> None:
        wallets = list(dict.fromkeys(wallet_addresses))
        for wallet_address in wallets:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_activity_daily(
                        wallet_address, activity_date, trades_count, markets_count, notional,
                        ingestion_run_id
                    )
                    SELECT
                        wallet_address,
                        trade_timestamp::date AS activity_date,
                        count(*)::integer AS trades_count,
                        count(DISTINCT condition_id)::integer AS markets_count,
                        COALESCE(sum(notional), 0) AS notional,
                        :run_id AS ingestion_run_id
                    FROM trades
                    WHERE wallet_address = :wallet_address
                        AND trade_timestamp IS NOT NULL
                    GROUP BY wallet_address, trade_timestamp::date
                    ON CONFLICT (wallet_address, activity_date) DO UPDATE SET
                        trades_count = EXCLUDED.trades_count,
                        markets_count = EXCLUDED.markets_count,
                        notional = EXCLUDED.notional,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {"wallet_address": wallet_address, "run_id": run_id},
            )
            self.connection.execute(
                text(
                    """
                    UPDATE wallets
                    SET
                        first_seen_at = stats.first_seen_at,
                        last_seen_at = stats.last_seen_at,
                        active_days_180d = stats.active_days_180d,
                        markets_count = stats.markets_count,
                        resolved_markets_count = stats.resolved_markets_count,
                        notional_30d = stats.notional_30d,
                        notional_90d = stats.notional_90d,
                        notional_180d = stats.notional_180d,
                        ingestion_run_id = :run_id,
                        updated_at = now()
                    FROM (
                        SELECT
                            min(t.trade_timestamp) AS first_seen_at,
                            max(t.trade_timestamp) AS last_seen_at,
                            count(DISTINCT t.trade_timestamp::date)
                                FILTER (WHERE t.trade_timestamp >= now() - interval '180 days')
                                ::integer AS active_days_180d,
                            count(DISTINCT t.condition_id)::integer AS markets_count,
                            count(DISTINCT wp.condition_id)::integer AS resolved_markets_count,
                            COALESCE(sum(t.notional)
                                FILTER (WHERE t.trade_timestamp >= now() - interval '30 days'), 0)
                                AS notional_30d,
                            COALESCE(sum(t.notional)
                                FILTER (WHERE t.trade_timestamp >= now() - interval '90 days'), 0)
                                AS notional_90d,
                            COALESCE(sum(t.notional)
                                FILTER (WHERE t.trade_timestamp >= now() - interval '180 days'), 0)
                                AS notional_180d
                        FROM trades t
                        LEFT JOIN wallet_positions_closed wp
                            ON wp.wallet_address = t.wallet_address
                            AND wp.condition_id = t.condition_id
                        WHERE t.wallet_address = :wallet_address
                    ) stats
                    WHERE wallets.wallet_address = :wallet_address
                    """
                ),
                {"wallet_address": wallet_address, "run_id": run_id},
            )

    def fetch_wallet_timeline(self, wallet_address: str, limit: int) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    trade_uid,
                    wallet_address,
                    proxy_wallet,
                    condition_id,
                    token_id,
                    side,
                    price,
                    size,
                    notional,
                    trade_timestamp,
                    transaction_hash,
                    taker_only,
                    raw
                FROM trades
                WHERE wallet_address = :wallet_address
                ORDER BY trade_timestamp DESC NULLS LAST, created_at DESC
                LIMIT :limit
                """
            ),
            {"wallet_address": wallet_address, "limit": limit},
        )
        return [dict(row._mapping) for row in result]

    def fetch_paper_wallets(self, limit: int) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                WITH latest_scores AS (
                    SELECT DISTINCT ON (wallet_address)
                        wallet_address, score, confidence, high_confidence_eligible
                    FROM wallet_scores
                    ORDER BY wallet_address, scored_at DESC
                ), targets AS (
                    SELECT
                        w.wallet_address,
                        (ww.wallet_address IS NOT NULL) AS watchlisted,
                        COALESCE(ls.score, 0) AS score,
                        COALESCE(ls.confidence, 0) AS confidence,
                        COALESCE(ls.high_confidence_eligible, false) AS high_confidence_eligible,
                        w.last_seen_at
                    FROM wallets w
                    LEFT JOIN watchlist_wallets ww
                        ON ww.wallet_address = w.wallet_address AND ww.status = 'active'
                    LEFT JOIN latest_scores ls ON ls.wallet_address = w.wallet_address
                    WHERE ww.wallet_address IS NOT NULL
                        OR ls.high_confidence_eligible = true
                        OR (ls.score >= 60 AND ls.confidence >= 0.35)
                )
                SELECT * FROM targets
                ORDER BY watchlisted DESC, high_confidence_eligible DESC,
                    score DESC, last_seen_at DESC NULLS LAST
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [dict(row._mapping) for row in result]

    def fetch_latest_trade_at(self, wallet_address: str) -> datetime | None:
        return self.connection.execute(
            text("SELECT max(trade_timestamp) FROM trades WHERE wallet_address = :wallet"),
            {"wallet": wallet_address},
        ).scalar_one()

    def fetch_paper_token_ids(
        self,
        *,
        limit: int,
        recent_hours: int = 168,
    ) -> list[str]:
        since = datetime.now(UTC) - timedelta(hours=recent_hours)
        result = self.connection.execute(
            text(
                """
                WITH latest_scores AS (
                    SELECT DISTINCT ON (wallet_address)
                        wallet_address, score, confidence, high_confidence_eligible
                    FROM wallet_scores
                    ORDER BY wallet_address, scored_at DESC
                ), target_wallets AS (
                    SELECT w.wallet_address
                    FROM wallets w
                    LEFT JOIN watchlist_wallets ww
                        ON ww.wallet_address = w.wallet_address AND ww.status = 'active'
                    LEFT JOIN latest_scores ls ON ls.wallet_address = w.wallet_address
                    WHERE ww.wallet_address IS NOT NULL
                        OR ls.high_confidence_eligible = true
                        OR (ls.score >= 60 AND ls.confidence >= 0.35)
                ), candidate_tokens AS (
                    SELECT mt.token_id, 0 AS priority, m.volume, mt.updated_at
                    FROM watchlist_markets wm
                    JOIN markets m ON m.condition_id = wm.condition_id
                    JOIN market_tokens mt ON mt.condition_id = wm.condition_id
                    WHERE wm.status = 'active'
                        AND COALESCE(m.active, true) = true
                        AND COALESCE(m.closed, false) = false
                    UNION ALL
                    SELECT t.token_id, 1 AS priority, m.volume, t.updated_at
                    FROM trades t
                    JOIN target_wallets tw ON tw.wallet_address = t.wallet_address
                    LEFT JOIN markets m ON m.condition_id = t.condition_id
                    WHERE t.token_id IS NOT NULL
                        AND t.trade_timestamp >= :since
                        AND COALESCE(m.closed, false) = false
                    UNION ALL
                    SELECT s.token_id, 2 AS priority, m.volume, s.updated_at
                    FROM signals s
                    LEFT JOIN markets m ON m.condition_id = s.market_id
                    WHERE s.processing_status = 'pending'
                        AND COALESCE(m.closed, false) = false
                )
                SELECT token_id
                FROM candidate_tokens
                WHERE token_id IS NOT NULL AND token_id <> ''
                GROUP BY token_id
                ORDER BY min(priority), max(COALESCE(volume, 0)) DESC,
                    max(updated_at) DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
        return [str(row.token_id) for row in result]
