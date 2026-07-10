from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, text


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class DashboardRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def fetch_top_wallets(
        self, *, limit: int, offset: int = 0, high_confidence_only: bool = False
    ) -> list[dict[str, Any]]:
        high_confidence_clause = "AND ws.high_confidence_eligible = true" if high_confidence_only else ""
        result = self.connection.execute(
            text(
                f"""
                WITH latest_scores AS (
                    SELECT *
                    FROM wallet_scores
                    WHERE scored_at = (SELECT max(scored_at) FROM wallet_scores)
                )
                SELECT
                    row_number() OVER (ORDER BY ws.score DESC, ws.confidence DESC, wf.realized_pnl_180d DESC)
                        AS rank,
                    ws.wallet_address,
                    ws.score,
                    ws.confidence,
                    ws.high_confidence_eligible,
                    ws.hard_gate_status,
                    ws.exclusion_reasons,
                    ws.component_summary,
                    ws.scored_at,
                    wf.n_resolved,
                    wf.active_days_180d,
                    wf.realized_notional_180d,
                    wf.realized_pnl_180d,
                    wf.net_roi_180d,
                    wf.bayes_wr,
                    wf.max_drawdown_ratio,
                    wf.single_market_pnl_share,
                    wf.avg_followability,
                    wf.avg_clv_10m
                FROM latest_scores ws
                JOIN wallet_features wf ON wf.feature_uid = ws.feature_uid
                WHERE true
                {high_confidence_clause}
                ORDER BY ws.score DESC, ws.confidence DESC, wf.realized_pnl_180d DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
        return [dict(row._mapping) for row in result]

    def count_top_wallets(self, *, high_confidence_only: bool = False) -> int:
        high_confidence_clause = "AND high_confidence_eligible = true" if high_confidence_only else ""
        result = self.connection.execute(
            text(
                f"""
                SELECT count(*)::integer
                FROM wallet_scores
                WHERE scored_at = (SELECT max(scored_at) FROM wallet_scores)
                {high_confidence_clause}
                """
            )
        ).scalar_one()
        return int(result)

    def fetch_wallet_detail(
        self, *, wallet_address: str, market_limit: int = 50, trade_limit: int = 50
    ) -> dict[str, Any]:
        return {
            "summary": self._fetch_wallet_summary(wallet_address),
            "score": self._fetch_wallet_score(wallet_address),
            "score_components": self._fetch_wallet_score_components(wallet_address),
            "equity_curve": self._fetch_wallet_equity(wallet_address),
            "category_distribution": self._fetch_wallet_category_distribution(wallet_address),
            "clv_distribution": self._fetch_wallet_clv_distribution(wallet_address),
            "recent_trades": self._fetch_wallet_recent_trades(wallet_address, trade_limit),
            "markets": self.fetch_wallet_markets(
                wallet_address=wallet_address, limit=market_limit, offset=0
            ),
        }

    def fetch_wallet_markets(
        self, *, wallet_address: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    wmr.result_uid,
                    wmr.wallet_address,
                    wmr.condition_id,
                    wmr.token_id,
                    wmr.outcome,
                    wmr.market_status,
                    wmr.result_status,
                    wmr.trade_count,
                    wmr.capital_deployed,
                    wmr.realized_pnl,
                    wmr.unrealized_pnl,
                    wmr.current_value,
                    wmr.net_pnl,
                    wmr.net_roi,
                    wmr.entry_time,
                    wmr.exit_time,
                    wmr.calculated_at,
                    m.gamma_market_id,
                    m.slug,
                    m.question,
                    m.category,
                    m.active,
                    m.closed,
                    m.end_date
                FROM wallet_market_results wmr
                LEFT JOIN markets m ON m.condition_id = wmr.condition_id
                WHERE wmr.wallet_address = :wallet_address
                ORDER BY abs(wmr.net_pnl) DESC, wmr.calculated_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"wallet_address": wallet_address, "limit": limit, "offset": offset},
        )
        return [dict(row._mapping) for row in result]

    def count_wallet_markets(self, *, wallet_address: str) -> int:
        result = self.connection.execute(
            text("SELECT count(*)::integer FROM wallet_market_results WHERE wallet_address = :wallet_address"),
            {"wallet_address": wallet_address},
        ).scalar_one()
        return int(result)

    def fetch_market_detail(self, *, market_id: str) -> dict[str, Any] | None:
        market = self.connection.execute(
            text(
                """
                SELECT
                    m.condition_id,
                    m.gamma_market_id,
                    m.gamma_event_id,
                    m.slug,
                    m.question,
                    m.category,
                    m.active,
                    m.closed,
                    m.archived,
                    m.accepting_orders,
                    m.end_date,
                    m.order_min_size,
                    m.order_price_min_tick_size,
                    m.volume,
                    m.liquidity,
                    e.title AS event_title,
                    e.slug AS event_slug
                FROM markets m
                LEFT JOIN events e ON e.gamma_event_id = m.gamma_event_id
                WHERE m.condition_id = :market_id
                    OR m.gamma_market_id = :market_id
                    OR m.slug = :market_id
                LIMIT 1
                """
            ),
            {"market_id": market_id},
        ).one_or_none()
        if market is None:
            return None
        condition_id = str(market.condition_id)
        return {
            "market": dict(market._mapping),
            "tokens": self._fetch_market_tokens(condition_id),
            "latest_orderbook": self._fetch_market_orderbook(condition_id),
            "top_holders": self._fetch_market_holders(condition_id),
            "smart_wallet_positions": self._fetch_market_smart_positions(condition_id, 50),
            "alerts": self.fetch_alerts(status=None, condition_id=condition_id, limit=20),
        }

    def fetch_markets(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                WITH latest_orderbook AS (
                    SELECT DISTINCT ON (condition_id)
                        condition_id,
                        snapshot_at,
                        best_bid,
                        best_ask,
                        midpoint,
                        spread,
                        spread_bps,
                        top_bid_depth,
                        top_ask_depth
                    FROM orderbook_top
                    WHERE condition_id IS NOT NULL
                    ORDER BY condition_id, snapshot_at DESC
                ),
                smart_flow AS (
                    SELECT
                        wpc.condition_id,
                        count(DISTINCT wpc.wallet_address)::integer AS smart_wallet_count,
                        COALESCE(sum(wpc.current_value), 0) AS smart_current_value
                    FROM wallet_positions_current wpc
                    JOIN wallet_scores ws ON ws.wallet_address = wpc.wallet_address
                    WHERE ws.scored_at = (SELECT max(scored_at) FROM wallet_scores)
                        AND (ws.high_confidence_eligible = true OR ws.score >= 70)
                    GROUP BY wpc.condition_id
                )
                SELECT
                    m.condition_id,
                    m.gamma_market_id,
                    m.slug,
                    m.question,
                    m.category,
                    m.active,
                    m.closed,
                    m.accepting_orders,
                    m.end_date,
                    m.volume,
                    m.liquidity,
                    lo.snapshot_at AS orderbook_snapshot_at,
                    lo.best_bid,
                    lo.best_ask,
                    lo.midpoint,
                    lo.spread,
                    lo.spread_bps,
                    lo.top_bid_depth,
                    lo.top_ask_depth,
                    COALESCE(sf.smart_wallet_count, 0) AS smart_wallet_count,
                    COALESCE(sf.smart_current_value, 0) AS smart_current_value
                FROM markets m
                LEFT JOIN latest_orderbook lo ON lo.condition_id = m.condition_id
                LEFT JOIN smart_flow sf ON sf.condition_id = m.condition_id
                ORDER BY COALESCE(m.volume, 0) DESC, m.updated_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
        return [dict(row._mapping) for row in result]

    def count_markets(self) -> int:
        return int(self.connection.execute(text("SELECT count(*)::integer FROM markets")).scalar_one())

    def fetch_market_smart_flow(
        self, *, market_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        condition_id = self._resolve_condition_id(market_id)
        if condition_id is None:
            return []
        return self._fetch_market_smart_positions(condition_id, limit, offset)

    def count_market_smart_flow(self, *, market_id: str) -> int:
        condition_id = self._resolve_condition_id(market_id)
        if condition_id is None:
            return 0
        result = self.connection.execute(
            text(
                """
                WITH latest_scores AS (
                    SELECT *
                    FROM wallet_scores
                    WHERE scored_at = (SELECT max(scored_at) FROM wallet_scores)
                ),
                flow AS (
                    SELECT wallet_address, token_id
                    FROM wallet_positions_current
                    WHERE condition_id = :condition_id
                    UNION ALL
                    SELECT wallet_address, token_id
                    FROM trades
                    WHERE condition_id = :condition_id
                        AND trade_timestamp >= now() - interval '7 days'
                    GROUP BY wallet_address, token_id
                )
                SELECT count(*)::integer
                FROM flow
                JOIN latest_scores ws ON ws.wallet_address = flow.wallet_address
                WHERE ws.high_confidence_eligible = true OR ws.score >= 70
                """
            ),
            {"condition_id": condition_id},
        ).scalar_one()
        return int(result)

    def fetch_latest_backtest_summary(self) -> dict[str, Any] | None:
        result = self.connection.execute(
            text(
                """
                SELECT
                    backtest_run_uid,
                    score_version,
                    training_start,
                    training_end,
                    validation_start,
                    validation_end,
                    strategy_config,
                    summary,
                    status,
                    started_at,
                    finished_at
                FROM backtest_runs
                ORDER BY finished_at DESC NULLS LAST, started_at DESC
                LIMIT 1
                """
            )
        ).one_or_none()
        return dict(result._mapping) if result else None

    def add_watchlist_wallet(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        wallet_address = str(payload["wallet_address"]).lower()
        row = {
            "wallet_address": wallet_address,
            "label": payload.get("label"),
            "reason": payload.get("reason"),
            "operator": payload.get("operator") or "local",
            "metadata": payload.get("metadata") or {},
        }
        self.connection.execute(
            text(
                """
                INSERT INTO watchlist_wallets(wallet_address, label, reason, status, operator, metadata)
                VALUES (:wallet_address, :label, :reason, 'active', :operator, CAST(:metadata AS jsonb))
                ON CONFLICT (wallet_address) DO UPDATE SET
                    label = EXCLUDED.label,
                    reason = EXCLUDED.reason,
                    status = 'active',
                    operator = EXCLUDED.operator,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """
            ),
            {**row, "metadata": _json(row["metadata"])},
        )
        self._audit(
            target_type="wallet",
            target_id=wallet_address,
            action="upsert_watchlist_wallet",
            operator=row["operator"],
            payload=row,
        )
        return self.fetch_watchlist_wallet(wallet_address) or row

    def add_watchlist_market(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        condition_id = str(payload["condition_id"])
        row = {
            "condition_id": condition_id,
            "label": payload.get("label"),
            "reason": payload.get("reason"),
            "operator": payload.get("operator") or "local",
            "metadata": payload.get("metadata") or {},
        }
        self.connection.execute(
            text(
                """
                INSERT INTO watchlist_markets(condition_id, label, reason, status, operator, metadata)
                VALUES (:condition_id, :label, :reason, 'active', :operator, CAST(:metadata AS jsonb))
                ON CONFLICT (condition_id) DO UPDATE SET
                    label = EXCLUDED.label,
                    reason = EXCLUDED.reason,
                    status = 'active',
                    operator = EXCLUDED.operator,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """
            ),
            {**row, "metadata": _json(row["metadata"])},
        )
        self._audit(
            target_type="market",
            target_id=condition_id,
            action="upsert_watchlist_market",
            operator=row["operator"],
            payload=row,
        )
        return self.fetch_watchlist_market(condition_id) or row

    def fetch_watchlist_wallet(self, wallet_address: str) -> dict[str, Any] | None:
        result = self.connection.execute(
            text("SELECT * FROM watchlist_wallets WHERE wallet_address = :wallet_address"),
            {"wallet_address": wallet_address.lower()},
        ).one_or_none()
        return dict(result._mapping) if result else None

    def fetch_watchlist_market(self, condition_id: str) -> dict[str, Any] | None:
        result = self.connection.execute(
            text("SELECT * FROM watchlist_markets WHERE condition_id = :condition_id"),
            {"condition_id": condition_id},
        ).one_or_none()
        return dict(result._mapping) if result else None

    def generate_alerts(self) -> dict[str, int]:
        counters = {
            "high_score_new_position": self._generate_high_score_new_position_alerts(),
            "crowded_smart_flow": self._generate_crowded_smart_flow_alerts(),
            "late_large_position": self._generate_late_large_position_alerts(),
            "liquidity_degradation": self._generate_liquidity_degradation_alerts(),
            "ingestion_delay": self._generate_ingestion_delay_alerts(),
        }
        return counters

    def fetch_alerts(
        self,
        *,
        status: str | None,
        limit: int,
        offset: int = 0,
        condition_id: str | None = None,
        wallet_address: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if condition_id:
            clauses.append("condition_id = :condition_id")
            params["condition_id"] = condition_id
        if wallet_address:
            clauses.append("wallet_address = :wallet_address")
            params["wallet_address"] = wallet_address.lower()
        where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
        result = self.connection.execute(
            text(
                f"""
                SELECT *
                FROM alert_events
                {where_clause}
                ORDER BY
                    CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                    last_seen_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in result]

    def count_alerts(
        self,
        *,
        status: str | None,
        condition_id: str | None = None,
        wallet_address: str | None = None,
    ) -> int:
        clauses = []
        params: dict[str, Any] = {}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if condition_id:
            clauses.append("condition_id = :condition_id")
            params["condition_id"] = condition_id
        if wallet_address:
            clauses.append("wallet_address = :wallet_address")
            params["wallet_address"] = wallet_address.lower()
        where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
        result = self.connection.execute(
            text(f"SELECT count(*)::integer FROM alert_events {where_clause}"),
            params,
        ).scalar_one()
        return int(result)

    def update_alert_status(self, *, alert_id: str, status: str, operator: str = "local") -> dict[str, Any] | None:
        if status not in {"open", "ack", "resolved"}:
            raise ValueError("alert status must be one of: open, ack, resolved")
        self.connection.execute(
            text(
                """
                UPDATE alert_events
                SET status = :status,
                    operator = :operator,
                    acknowledged_at = CASE WHEN :status = 'ack' THEN now() ELSE acknowledged_at END,
                    resolved_at = CASE WHEN :status = 'resolved' THEN now() ELSE NULL END,
                    updated_at = now()
                WHERE alert_id = :alert_id
                """
            ),
            {"alert_id": alert_id, "status": status, "operator": operator},
        )
        result = self.connection.execute(
            text("SELECT * FROM alert_events WHERE alert_id = :alert_id"),
            {"alert_id": alert_id},
        ).one_or_none()
        return dict(result._mapping) if result else None

    def _fetch_wallet_summary(self, wallet_address: str) -> dict[str, Any] | None:
        result = self.connection.execute(
            text(
                """
                WITH pnl AS (
                    SELECT
                        wallet_address,
                        count(*)::integer AS markets_count,
                        count(*) FILTER (WHERE result_status IN ('closed', 'settled'))::integer
                            AS closed_markets_count,
                        COALESCE(sum(realized_pnl), 0) AS realized_pnl,
                        COALESCE(sum(unrealized_pnl), 0) AS unrealized_pnl,
                        COALESCE(sum(current_value), 0) AS current_value,
                        COALESCE(sum(net_pnl), 0) AS net_pnl,
                        COALESCE(sum(capital_deployed), 0) AS capital_deployed
                    FROM wallet_market_results
                    WHERE wallet_address = :wallet_address
                    GROUP BY wallet_address
                ),
                equity AS (
                    SELECT DISTINCT ON (wallet_address)
                        wallet_address,
                        max_drawdown
                    FROM wallet_daily_equity
                    WHERE wallet_address = :wallet_address
                    ORDER BY wallet_address, equity_date DESC
                )
                SELECT
                    w.wallet_address,
                    w.first_seen_at,
                    w.last_seen_at,
                    w.active_days_180d,
                    w.notional_30d,
                    w.notional_90d,
                    w.notional_180d,
                    COALESCE(p.markets_count, 0) AS markets_count,
                    COALESCE(p.closed_markets_count, 0) AS closed_markets_count,
                    COALESCE(p.realized_pnl, 0) AS realized_pnl,
                    COALESCE(p.unrealized_pnl, 0) AS unrealized_pnl,
                    COALESCE(p.current_value, 0) AS current_value,
                    COALESCE(p.net_pnl, 0) AS net_pnl,
                    COALESCE(p.capital_deployed, 0) AS capital_deployed,
                    CASE WHEN COALESCE(p.capital_deployed, 0) = 0 THEN NULL
                        ELSE p.net_pnl / p.capital_deployed
                    END AS net_roi,
                    COALESCE(e.max_drawdown, 0) AS max_drawdown
                FROM wallets w
                LEFT JOIN pnl p ON p.wallet_address = w.wallet_address
                LEFT JOIN equity e ON e.wallet_address = w.wallet_address
                WHERE w.wallet_address = :wallet_address
                """
            ),
            {"wallet_address": wallet_address},
        ).one_or_none()
        return dict(result._mapping) if result else None

    def _fetch_wallet_score(self, wallet_address: str) -> dict[str, Any] | None:
        result = self.connection.execute(
            text(
                """
                SELECT
                    ws.score_uid,
                    ws.wallet_address,
                    ws.score,
                    ws.raw_score,
                    ws.confidence,
                    ws.high_confidence_eligible,
                    ws.hard_gate_status,
                    ws.exclusion_reasons,
                    ws.penalty_summary,
                    ws.component_summary,
                    ws.scored_at,
                    wf.n_resolved,
                    wf.active_days_180d,
                    wf.realized_notional_180d,
                    wf.realized_pnl_180d,
                    wf.net_roi_180d,
                    wf.bayes_wr,
                    wf.max_drawdown_ratio,
                    wf.avg_followability
                FROM wallet_scores ws
                JOIN wallet_features wf ON wf.feature_uid = ws.feature_uid
                WHERE ws.wallet_address = :wallet_address
                ORDER BY ws.scored_at DESC
                LIMIT 1
                """
            ),
            {"wallet_address": wallet_address},
        ).one_or_none()
        return dict(result._mapping) if result else None

    def _fetch_wallet_score_components(self, wallet_address: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT c.component_name, c.component_score, c.max_score, c.details
                FROM wallet_score_components c
                JOIN wallet_scores ws ON ws.score_uid = c.score_uid
                WHERE ws.wallet_address = :wallet_address
                    AND ws.scored_at = (
                        SELECT max(scored_at) FROM wallet_scores WHERE wallet_address = :wallet_address
                    )
                ORDER BY c.max_score DESC, c.component_name
                """
            ),
            {"wallet_address": wallet_address},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_wallet_equity(self, wallet_address: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    equity_date,
                    realized_pnl_cumulative,
                    unrealized_pnl,
                    net_pnl,
                    capital_deployed,
                    daily_volume,
                    trades_count,
                    drawdown,
                    max_drawdown
                FROM wallet_daily_equity
                WHERE wallet_address = :wallet_address
                ORDER BY equity_date DESC
                LIMIT 180
                """
            ),
            {"wallet_address": wallet_address},
        )
        rows = [dict(row._mapping) for row in result]
        return list(reversed(rows))

    def _fetch_wallet_category_distribution(self, wallet_address: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    COALESCE(m.category, 'unknown') AS category,
                    count(*)::integer AS markets_count,
                    COALESCE(sum(wmr.capital_deployed), 0) AS capital_deployed,
                    COALESCE(sum(wmr.net_pnl), 0) AS net_pnl
                FROM wallet_market_results wmr
                LEFT JOIN markets m ON m.condition_id = wmr.condition_id
                WHERE wmr.wallet_address = :wallet_address
                GROUP BY COALESCE(m.category, 'unknown')
                ORDER BY abs(COALESCE(sum(wmr.net_pnl), 0)) DESC
                """
            ),
            {"wallet_address": wallet_address},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_wallet_clv_distribution(self, wallet_address: str) -> dict[str, Any]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    count(*)::integer AS sample_count,
                    avg(clv_30s) AS avg_clv_30s,
                    avg(clv_2m) AS avg_clv_2m,
                    avg(clv_10m) AS avg_clv_10m,
                    avg(clv_1h) AS avg_clv_1h,
                    avg(clv_24h) AS avg_clv_24h,
                    percentile_disc(0.25) WITHIN GROUP (ORDER BY clv_10m) AS p25_clv_10m,
                    percentile_disc(0.50) WITHIN GROUP (ORDER BY clv_10m) AS p50_clv_10m,
                    percentile_disc(0.75) WITHIN GROUP (ORDER BY clv_10m) AS p75_clv_10m,
                    avg(CASE WHEN clv_10m > 0 THEN 1 ELSE 0 END) AS positive_clv_10m_share
                FROM trade_clv_metrics
                WHERE wallet_address = :wallet_address
                    AND clv_10m IS NOT NULL
                """
            ),
            {"wallet_address": wallet_address},
        ).one()
        return dict(result._mapping)

    def _fetch_wallet_recent_trades(self, wallet_address: str, limit: int) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    t.trade_uid,
                    t.condition_id,
                    t.token_id,
                    mt.outcome,
                    m.question,
                    t.side,
                    t.price,
                    t.size,
                    t.notional,
                    t.trade_timestamp,
                    t.transaction_hash
                FROM trades t
                LEFT JOIN market_tokens mt ON mt.token_id = t.token_id
                LEFT JOIN markets m ON m.condition_id = t.condition_id
                WHERE t.wallet_address = :wallet_address
                ORDER BY t.trade_timestamp DESC NULLS LAST, t.created_at DESC
                LIMIT :limit
                """
            ),
            {"wallet_address": wallet_address, "limit": limit},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_market_tokens(self, condition_id: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT token_id, condition_id, gamma_market_id, outcome_index, outcome, mapping_status,
                    mapping_error, verified_at
                FROM market_tokens
                WHERE condition_id = :condition_id
                ORDER BY outcome_index
                """
            ),
            {"condition_id": condition_id},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_market_orderbook(self, condition_id: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT DISTINCT ON (ot.asset_id)
                    ot.asset_id,
                    mt.outcome,
                    ot.snapshot_at,
                    ot.best_bid,
                    ot.best_ask,
                    ot.best_bid_size,
                    ot.best_ask_size,
                    ot.midpoint,
                    ot.spread,
                    ot.spread_bps,
                    ot.top_bid_depth,
                    ot.top_ask_depth,
                    mf.market_liquidity_score,
                    mf.buy_fillable,
                    mf.sell_fillable,
                    mf.spread_too_wide,
                    mf.depth_insufficient,
                    mf.price_missing
                FROM orderbook_top ot
                LEFT JOIN market_tokens mt ON mt.token_id = ot.asset_id
                LEFT JOIN market_followability_snapshots mf ON mf.snapshot_uid = ot.snapshot_uid
                WHERE ot.condition_id = :condition_id
                ORDER BY ot.asset_id, ot.snapshot_at DESC
                """
            ),
            {"condition_id": condition_id},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_market_holders(self, condition_id: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT DISTINCT ON (wallet_address, token_id)
                    wallet_address,
                    token_id,
                    holder_rank,
                    amount,
                    outcome_index,
                    pseudonym,
                    display_name,
                    snapshot_at
                FROM market_holders
                WHERE condition_id = :condition_id
                ORDER BY wallet_address, token_id, snapshot_at DESC
                LIMIT 100
                """
            ),
            {"condition_id": condition_id},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_market_smart_positions(
        self, condition_id: str, limit: int, offset: int = 0
    ) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                WITH latest_scores AS (
                    SELECT *
                    FROM wallet_scores
                    WHERE scored_at = (SELECT max(scored_at) FROM wallet_scores)
                ),
                current_positions AS (
                    SELECT
                        wallet_address,
                        condition_id,
                        token_id,
                        outcome,
                        size,
                        initial_value,
                        current_value,
                        cash_pnl,
                        cur_price,
                        snapshot_at,
                        NULL::numeric AS recent_notional,
                        NULL::timestamptz AS last_trade_at
                    FROM wallet_positions_current
                    WHERE condition_id = :condition_id
                ),
                recent_trades AS (
                    SELECT
                        wallet_address,
                        condition_id,
                        token_id,
                        NULL::text AS outcome,
                        NULL::numeric AS size,
                        NULL::numeric AS initial_value,
                        NULL::numeric AS current_value,
                        NULL::numeric AS cash_pnl,
                        NULL::numeric AS cur_price,
                        NULL::timestamptz AS snapshot_at,
                        COALESCE(sum(notional), 0) AS recent_notional,
                        max(trade_timestamp) AS last_trade_at
                    FROM trades
                    WHERE condition_id = :condition_id
                        AND trade_timestamp >= now() - interval '7 days'
                    GROUP BY wallet_address, condition_id, token_id
                )
                SELECT
                    flow.wallet_address,
                    flow.condition_id,
                    flow.token_id,
                    flow.outcome,
                    flow.size,
                    flow.initial_value,
                    flow.current_value,
                    flow.cash_pnl,
                    flow.cur_price,
                    flow.snapshot_at,
                    flow.recent_notional,
                    flow.last_trade_at,
                    ws.score,
                    ws.confidence,
                    ws.high_confidence_eligible,
                    ws.exclusion_reasons
                FROM (
                    SELECT * FROM current_positions
                    UNION ALL
                    SELECT * FROM recent_trades
                ) flow
                JOIN latest_scores ws ON ws.wallet_address = flow.wallet_address
                WHERE ws.high_confidence_eligible = true OR ws.score >= 70
                ORDER BY ws.score DESC, COALESCE(flow.current_value, flow.recent_notional, 0) DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"condition_id": condition_id, "limit": limit, "offset": offset},
        )
        return [dict(row._mapping) for row in result]

    def _resolve_condition_id(self, market_id: str) -> str | None:
        result = self.connection.execute(
            text(
                """
                SELECT condition_id
                FROM markets
                WHERE condition_id = :market_id
                    OR gamma_market_id = :market_id
                    OR slug = :market_id
                LIMIT 1
                """
            ),
            {"market_id": market_id},
        ).one_or_none()
        return str(result.condition_id) if result else None

    def _audit(
        self,
        *,
        target_type: str,
        target_id: str,
        action: str,
        operator: str,
        payload: Mapping[str, Any],
    ) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO watchlist_audit_log(target_type, target_id, action, operator, payload)
                VALUES (:target_type, :target_id, :action, :operator, CAST(:payload AS jsonb))
                """
            ),
            {
                "target_type": target_type,
                "target_id": target_id,
                "action": action,
                "operator": operator,
                "payload": _json(payload),
            },
        )

    def _upsert_alerts_from_query(self, query: str) -> int:
        result = self.connection.execute(text(query))
        return int(result.rowcount or 0)

    def _generate_high_score_new_position_alerts(self) -> int:
        return self._upsert_alerts_from_query(
            """
            WITH latest_scores AS (
                SELECT * FROM wallet_scores WHERE scored_at = (SELECT max(scored_at) FROM wallet_scores)
            ),
            candidates AS (
                SELECT
                    wpc.wallet_address,
                    wpc.condition_id,
                    wpc.token_id,
                    wpc.outcome,
                    wpc.current_value,
                    wpc.snapshot_at,
                    ws.score,
                    ws.confidence,
                    m.question
                FROM wallet_positions_current wpc
                JOIN latest_scores ws ON ws.wallet_address = wpc.wallet_address
                LEFT JOIN markets m ON m.condition_id = wpc.condition_id
                WHERE wpc.snapshot_at >= now() - interval '7 days'
                    AND (ws.high_confidence_eligible = true OR ws.score >= 70)
            )
            INSERT INTO alert_events(
                alert_id, alert_type, severity, status, wallet_address, condition_id, token_id,
                title, message, evidence, first_seen_at, last_seen_at
            )
            SELECT
                md5(concat_ws('|', 'high_score_new_position', wallet_address, condition_id, token_id)),
                'high_score_new_position',
                'info',
                'open',
                wallet_address,
                condition_id,
                token_id,
                '高分钱包新建仓',
                concat('钱包 ', wallet_address, ' 在市场 ', COALESCE(question, condition_id), ' 持有 ', COALESCE(outcome, token_id)),
                jsonb_build_object(
                    'score', score,
                    'confidence', confidence,
                    'current_value', current_value,
                    'snapshot_at', snapshot_at
                ),
                snapshot_at,
                snapshot_at
            FROM candidates
            ON CONFLICT (alert_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                evidence = EXCLUDED.evidence,
                updated_at = now()
            """
        )

    def _generate_crowded_smart_flow_alerts(self) -> int:
        return self._upsert_alerts_from_query(
            """
            WITH latest_scores AS (
                SELECT * FROM wallet_scores WHERE scored_at = (SELECT max(scored_at) FROM wallet_scores)
            ),
            crowded AS (
                SELECT
                    wpc.condition_id,
                    count(DISTINCT wpc.wallet_address)::integer AS smart_wallet_count,
                    COALESCE(sum(wpc.current_value), 0) AS current_value,
                    max(wpc.snapshot_at) AS last_seen_at,
                    max(m.question) AS question
                FROM wallet_positions_current wpc
                JOIN latest_scores ws ON ws.wallet_address = wpc.wallet_address
                LEFT JOIN markets m ON m.condition_id = wpc.condition_id
                WHERE ws.high_confidence_eligible = true OR ws.score >= 70
                GROUP BY wpc.condition_id
                HAVING count(DISTINCT wpc.wallet_address) >= 2
            )
            INSERT INTO alert_events(
                alert_id, alert_type, severity, status, condition_id, title, message,
                evidence, first_seen_at, last_seen_at
            )
            SELECT
                md5(concat_ws('|', 'crowded_smart_flow', condition_id)),
                'crowded_smart_flow',
                'warning',
                'open',
                condition_id,
                '多个高分钱包同向进入市场',
                concat(smart_wallet_count, ' 个高分钱包持有市场 ', COALESCE(question, condition_id)),
                jsonb_build_object(
                    'smart_wallet_count', smart_wallet_count,
                    'current_value', current_value
                ),
                last_seen_at,
                last_seen_at
            FROM crowded
            ON CONFLICT (alert_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                evidence = EXCLUDED.evidence,
                updated_at = now()
            """
        )

    def _generate_late_large_position_alerts(self) -> int:
        return self._upsert_alerts_from_query(
            """
            WITH candidates AS (
                SELECT
                    wpc.wallet_address,
                    wpc.condition_id,
                    wpc.token_id,
                    wpc.outcome,
                    GREATEST(COALESCE(wpc.current_value, 0), COALESCE(wpc.initial_value, 0)) AS exposure,
                    wpc.snapshot_at,
                    m.question,
                    m.end_date
                FROM wallet_positions_current wpc
                JOIN markets m ON m.condition_id = wpc.condition_id
                WHERE m.end_date BETWEEN now() AND now() + interval '3 days'
                    AND GREATEST(COALESCE(wpc.current_value, 0), COALESCE(wpc.initial_value, 0)) >= 1000
            )
            INSERT INTO alert_events(
                alert_id, alert_type, severity, status, wallet_address, condition_id, token_id,
                title, message, evidence, first_seen_at, last_seen_at
            )
            SELECT
                md5(concat_ws('|', 'late_large_position', wallet_address, condition_id, token_id)),
                'late_large_position',
                'warning',
                'open',
                wallet_address,
                condition_id,
                token_id,
                '临近结束大额建仓',
                concat('钱包 ', wallet_address, ' 在临近结束市场持仓约 ', exposure),
                jsonb_build_object('exposure', exposure, 'end_date', end_date, 'question', question),
                snapshot_at,
                snapshot_at
            FROM candidates
            ON CONFLICT (alert_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                evidence = EXCLUDED.evidence,
                updated_at = now()
            """
        )

    def _generate_liquidity_degradation_alerts(self) -> int:
        return self._upsert_alerts_from_query(
            """
            WITH latest_followability AS (
                SELECT DISTINCT ON (asset_id)
                    asset_id,
                    condition_id,
                    snapshot_at,
                    spread_bps,
                    top_bid_depth,
                    top_ask_depth,
                    market_liquidity_score,
                    spread_too_wide,
                    depth_insufficient,
                    price_missing
                FROM market_followability_snapshots
                ORDER BY asset_id, snapshot_at DESC
            ),
            candidates AS (
                SELECT lf.*, m.question
                FROM latest_followability lf
                LEFT JOIN markets m ON m.condition_id = lf.condition_id
                WHERE lf.spread_too_wide OR lf.depth_insufficient OR lf.price_missing
            )
            INSERT INTO alert_events(
                alert_id, alert_type, severity, status, condition_id, token_id,
                title, message, evidence, first_seen_at, last_seen_at
            )
            SELECT
                md5(concat_ws('|', 'liquidity_degradation', asset_id)),
                'liquidity_degradation',
                'warning',
                'open',
                condition_id,
                asset_id,
                'spread 或深度恶化',
                concat('市场 ', COALESCE(question, condition_id), ' 的 token ', asset_id, ' 可跟随性变差'),
                jsonb_build_object(
                    'spread_bps', spread_bps,
                    'top_bid_depth', top_bid_depth,
                    'top_ask_depth', top_ask_depth,
                    'market_liquidity_score', market_liquidity_score,
                    'spread_too_wide', spread_too_wide,
                    'depth_insufficient', depth_insufficient,
                    'price_missing', price_missing
                ),
                snapshot_at,
                snapshot_at
            FROM candidates
            ON CONFLICT (alert_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                evidence = EXCLUDED.evidence,
                updated_at = now()
            """
        )

    def _generate_ingestion_delay_alerts(self) -> int:
        return self._upsert_alerts_from_query(
            """
            WITH latest_runs AS (
                SELECT
                    job_name,
                    max(COALESCE(finished_at, started_at)) AS last_seen_at
                FROM ingestion_runs
                GROUP BY job_name
            ),
            delayed AS (
                SELECT *
                FROM latest_runs
                WHERE last_seen_at < now() - interval '6 hours'
            )
            INSERT INTO alert_events(
                alert_id, alert_type, severity, status, title, message,
                evidence, first_seen_at, last_seen_at
            )
            SELECT
                md5(concat_ws('|', 'ingestion_delay', job_name)),
                'ingestion_delay',
                'critical',
                'open',
                '数据采集延迟超过阈值',
                concat('任务 ', job_name, ' 最近一次完成时间超过 6 小时'),
                jsonb_build_object('job_name', job_name, 'last_seen_at', last_seen_at),
                last_seen_at,
                last_seen_at
            FROM delayed
            ON CONFLICT (alert_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                evidence = EXCLUDED.evidence,
                updated_at = now()
            """
        )
