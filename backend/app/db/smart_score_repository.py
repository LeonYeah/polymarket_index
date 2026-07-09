from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from backend.app.analytics.smart_score import SmartScoreResult, stable_uid


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class SmartScoreRepository:
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

    def fetch_feature_rows(
        self,
        *,
        run_id: str,
        feature_version: str,
        as_of: datetime,
        observation_start: datetime,
        wallet_limit: int | None,
    ) -> list[dict[str, Any]]:
        limit_clause = "LIMIT :wallet_limit" if wallet_limit is not None else ""
        result = self.connection.execute(
            text(
                f"""
                WITH candidate_wallets AS (
                    SELECT wallet_address, max(updated_at) AS last_updated_at
                    FROM (
                        SELECT wallet_address, updated_at FROM wallet_market_results
                        UNION ALL
                        SELECT wallet_address, updated_at FROM trades
                    ) candidates
                    GROUP BY wallet_address
                    ORDER BY last_updated_at DESC NULLS LAST, wallet_address
                    {limit_clause}
                ),
                result_window AS (
                    SELECT wmr.*
                    FROM wallet_market_results wmr
                    JOIN candidate_wallets cw ON cw.wallet_address = wmr.wallet_address
                    WHERE COALESCE(wmr.exit_time, wmr.entry_time, wmr.calculated_at) >= :observation_start
                        AND COALESCE(wmr.exit_time, wmr.entry_time, wmr.calculated_at) <= :as_of
                ),
                result_stats AS (
                    SELECT
                        wallet_address,
                        count(*) FILTER (WHERE result_status IN ('closed', 'settled'))::integer AS n_resolved,
                        COALESCE(sum(capital_deployed) FILTER (WHERE result_status IN ('closed', 'settled')), 0)
                            AS realized_notional_180d,
                        COALESCE(sum(realized_pnl) FILTER (WHERE result_status IN ('closed', 'settled')), 0)
                            AS realized_pnl_180d,
                        COALESCE(sum(unrealized_pnl) FILTER (WHERE result_status = 'open'), 0)
                            AS open_unrealized_pnl,
                        COALESCE(sum(capital_deployed), 0) AS capital_deployed_180d,
                        COALESCE(sum(realized_pnl) FILTER (WHERE realized_pnl > 0), 0) AS gross_profit_180d,
                        abs(COALESCE(sum(realized_pnl) FILTER (WHERE realized_pnl < 0), 0)) AS gross_loss_180d,
                        count(*) FILTER (WHERE realized_pnl > 0)::integer AS wins_count,
                        count(*) FILTER (WHERE realized_pnl < 0)::integer AS losses_count,
                        COALESCE(max(realized_pnl), 0) AS best_market_pnl
                    FROM result_window
                    GROUP BY wallet_address
                ),
                active_stats AS (
                    SELECT
                        wallet_address,
                        count(DISTINCT trade_timestamp::date)::integer AS active_days_180d
                    FROM trades
                    WHERE trade_timestamp >= :observation_start
                        AND trade_timestamp <= :as_of
                    GROUP BY wallet_address
                ),
                trade_notional_stats AS (
                    SELECT
                        wallet_address,
                        COALESCE(sum(COALESCE(notional, price * size)), 0) AS realized_notional_180d
                    FROM trades
                    WHERE trade_timestamp >= :observation_start
                        AND trade_timestamp <= :as_of
                    GROUP BY wallet_address
                ),
                equity_stats AS (
                    SELECT DISTINCT ON (wallet_address)
                        wallet_address,
                        max_drawdown
                    FROM wallet_daily_equity
                    WHERE equity_date <= :as_of_date
                    ORDER BY wallet_address, equity_date DESC
                ),
                clv_stats AS (
                    SELECT
                        wallet_address,
                        avg(clv_30s) AS avg_clv_30s,
                        avg(clv_2m) AS avg_clv_2m,
                        avg(clv_10m) AS avg_clv_10m,
                        avg(clv_1h) AS avg_clv_1h,
                        avg(clv_24h) AS avg_clv_24h,
                        avg(
                            CASE
                                WHEN COALESCE(clv_10m, clv_2m, clv_30s) > 0 THEN 1
                                WHEN COALESCE(clv_10m, clv_2m, clv_30s) IS NULL THEN NULL
                                ELSE 0
                            END
                        ) AS positive_clv_share,
                        count(*) FILTER (
                            WHERE clv_30s IS NOT NULL
                                OR clv_2m IS NOT NULL
                                OR clv_10m IS NOT NULL
                                OR clv_1h IS NOT NULL
                                OR clv_24h IS NOT NULL
                        )::integer AS clv_sample_count
                    FROM trade_clv_metrics
                    WHERE trade_timestamp >= :observation_start
                        AND trade_timestamp <= :as_of
                    GROUP BY wallet_address
                ),
                followability_stats AS (
                    SELECT
                        t.wallet_address,
                        avg(mfs.market_liquidity_score) AS avg_followability,
                        avg(CASE WHEN mfs.market_liquidity_score < 60 THEN 1 ELSE 0 END)
                            AS low_liquidity_trade_share
                    FROM trades t
                    JOIN LATERAL (
                        SELECT market_liquidity_score
                        FROM market_followability_snapshots mfs
                        WHERE mfs.asset_id = t.token_id
                            AND mfs.snapshot_at <= LEAST(COALESCE(t.trade_timestamp, :as_of), :as_of)
                        ORDER BY mfs.snapshot_at DESC
                        LIMIT 1
                    ) mfs ON true
                    WHERE t.trade_timestamp >= :observation_start
                        AND t.trade_timestamp <= :as_of
                    GROUP BY t.wallet_address
                )
                SELECT
                    cw.wallet_address,
                    :feature_version AS feature_version,
                    :as_of AS as_of,
                    :observation_start AS observation_start,
                    :as_of AS observation_end,
                    COALESCE(rs.n_resolved, 0) AS n_resolved,
                    COALESCE(ast.active_days_180d, 0) AS active_days_180d,
                    COALESCE(tns.realized_notional_180d, 0) AS realized_notional_180d,
                    COALESCE(rs.realized_pnl_180d, 0) AS realized_pnl_180d,
                    COALESCE(rs.open_unrealized_pnl, 0) AS open_unrealized_pnl,
                    COALESCE(rs.capital_deployed_180d, 0) AS capital_deployed_180d,
                    CASE WHEN COALESCE(rs.capital_deployed_180d, 0) = 0 THEN NULL
                        ELSE (COALESCE(rs.realized_pnl_180d, 0) + COALESCE(rs.open_unrealized_pnl, 0))
                            / rs.capital_deployed_180d
                    END AS net_roi_180d,
                    COALESCE(rs.gross_profit_180d, 0) AS gross_profit_180d,
                    COALESCE(rs.gross_loss_180d, 0) AS gross_loss_180d,
                    CASE WHEN COALESCE(rs.gross_loss_180d, 0) = 0 THEN NULL
                        ELSE rs.gross_profit_180d / rs.gross_loss_180d
                    END AS profit_factor,
                    CASE WHEN COALESCE(rs.wins_count, 0) + COALESCE(rs.losses_count, 0) = 0 THEN NULL
                        ELSE rs.wins_count::numeric / (rs.wins_count + rs.losses_count)
                    END AS win_rate,
                    (COALESCE(rs.wins_count, 0) + 11)::numeric
                        / (COALESCE(rs.wins_count, 0) + COALESCE(rs.losses_count, 0) + 20) AS bayes_wr,
                    COALESCE(es.max_drawdown, 0) AS max_drawdown,
                    CASE WHEN COALESCE(rs.capital_deployed_180d, 0) = 0 THEN 0
                        ELSE COALESCE(es.max_drawdown, 0) / rs.capital_deployed_180d
                    END AS max_drawdown_ratio,
                    CASE WHEN COALESCE(rs.gross_profit_180d, 0) = 0 THEN 0
                        ELSE COALESCE(rs.best_market_pnl, 0) / rs.gross_profit_180d
                    END AS single_market_pnl_share,
                    cs.avg_clv_30s,
                    cs.avg_clv_2m,
                    cs.avg_clv_10m,
                    cs.avg_clv_1h,
                    cs.avg_clv_24h,
                    cs.positive_clv_share,
                    COALESCE(cs.clv_sample_count, 0) AS clv_sample_count,
                    COALESCE(fs.avg_followability, 0) AS avg_followability,
                    COALESCE(fs.low_liquidity_trade_share, 1) AS low_liquidity_trade_share,
                    :as_of AS calculated_at,
                    'smart_score_v1' AS source,
                    :run_id AS ingestion_run_id
                FROM candidate_wallets cw
                LEFT JOIN result_stats rs ON rs.wallet_address = cw.wallet_address
                LEFT JOIN active_stats ast ON ast.wallet_address = cw.wallet_address
                LEFT JOIN trade_notional_stats tns ON tns.wallet_address = cw.wallet_address
                LEFT JOIN equity_stats es ON es.wallet_address = cw.wallet_address
                LEFT JOIN clv_stats cs ON cs.wallet_address = cw.wallet_address
                LEFT JOIN followability_stats fs ON fs.wallet_address = cw.wallet_address
                ORDER BY cw.last_updated_at DESC NULLS LAST, cw.wallet_address
                """
            ),
            {
                "run_id": run_id,
                "feature_version": feature_version,
                "as_of": as_of,
                "as_of_date": as_of.date(),
                "observation_start": observation_start,
                "wallet_limit": wallet_limit,
            },
        )
        rows = [dict(row._mapping) for row in result]
        for row in rows:
            row["feature_uid"] = stable_uid(
                ["wallet_features", row["wallet_address"], feature_version, as_of]
            )
            row["input_snapshot"] = {
                "source_tables": [
                    "wallet_market_results",
                    "wallet_daily_equity",
                    "trade_clv_metrics",
                    "market_followability_snapshots",
                    "trades",
                ],
                "lookback_days": (as_of - observation_start).days,
            }
        return rows

    def upsert_wallet_features(self, rows: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_features(
                        feature_uid, wallet_address, feature_version, as_of, observation_start,
                        observation_end, n_resolved, active_days_180d, realized_notional_180d,
                        realized_pnl_180d, open_unrealized_pnl, capital_deployed_180d,
                        net_roi_180d, gross_profit_180d, gross_loss_180d, profit_factor,
                        win_rate, bayes_wr, max_drawdown, max_drawdown_ratio,
                        single_market_pnl_share, avg_clv_30s, avg_clv_2m, avg_clv_10m,
                        avg_clv_1h, avg_clv_24h, positive_clv_share, clv_sample_count,
                        avg_followability, low_liquidity_trade_share, input_snapshot,
                        calculated_at, source, ingestion_run_id
                    )
                    VALUES (
                        :feature_uid, :wallet_address, :feature_version, :as_of,
                        :observation_start, :observation_end, :n_resolved, :active_days_180d,
                        :realized_notional_180d, :realized_pnl_180d, :open_unrealized_pnl,
                        :capital_deployed_180d, :net_roi_180d, :gross_profit_180d,
                        :gross_loss_180d, :profit_factor, :win_rate, :bayes_wr, :max_drawdown,
                        :max_drawdown_ratio, :single_market_pnl_share, :avg_clv_30s,
                        :avg_clv_2m, :avg_clv_10m, :avg_clv_1h, :avg_clv_24h,
                        :positive_clv_share, :clv_sample_count, :avg_followability,
                        :low_liquidity_trade_share, CAST(:input_snapshot AS jsonb),
                        :calculated_at, :source, :run_id
                    )
                    ON CONFLICT (wallet_address, feature_version, as_of) DO UPDATE SET
                        n_resolved = EXCLUDED.n_resolved,
                        active_days_180d = EXCLUDED.active_days_180d,
                        realized_notional_180d = EXCLUDED.realized_notional_180d,
                        realized_pnl_180d = EXCLUDED.realized_pnl_180d,
                        open_unrealized_pnl = EXCLUDED.open_unrealized_pnl,
                        capital_deployed_180d = EXCLUDED.capital_deployed_180d,
                        net_roi_180d = EXCLUDED.net_roi_180d,
                        gross_profit_180d = EXCLUDED.gross_profit_180d,
                        gross_loss_180d = EXCLUDED.gross_loss_180d,
                        profit_factor = EXCLUDED.profit_factor,
                        win_rate = EXCLUDED.win_rate,
                        bayes_wr = EXCLUDED.bayes_wr,
                        max_drawdown = EXCLUDED.max_drawdown,
                        max_drawdown_ratio = EXCLUDED.max_drawdown_ratio,
                        single_market_pnl_share = EXCLUDED.single_market_pnl_share,
                        avg_clv_30s = EXCLUDED.avg_clv_30s,
                        avg_clv_2m = EXCLUDED.avg_clv_2m,
                        avg_clv_10m = EXCLUDED.avg_clv_10m,
                        avg_clv_1h = EXCLUDED.avg_clv_1h,
                        avg_clv_24h = EXCLUDED.avg_clv_24h,
                        positive_clv_share = EXCLUDED.positive_clv_share,
                        clv_sample_count = EXCLUDED.clv_sample_count,
                        avg_followability = EXCLUDED.avg_followability,
                        low_liquidity_trade_share = EXCLUDED.low_liquidity_trade_share,
                        input_snapshot = EXCLUDED.input_snapshot,
                        calculated_at = EXCLUDED.calculated_at,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**row, "run_id": run_id, "input_snapshot": _json(row.get("input_snapshot", {}))},
            )
            count += 1
        return count

    def upsert_wallet_scores(
        self,
        results: Iterable[SmartScoreResult],
        *,
        run_id: str,
        scored_at: datetime,
        weight_config: Mapping[str, Any],
    ) -> int:
        count = 0
        for result in results:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_scores(
                        score_uid, wallet_address, feature_uid, score_version, score, raw_score,
                        confidence, high_confidence_eligible, hard_gate_status, exclusion_reasons,
                        penalty_summary, component_summary, weight_config, scored_at, source,
                        ingestion_run_id
                    )
                    VALUES (
                        :score_uid, :wallet_address, :feature_uid, :score_version, :score,
                        :raw_score, :confidence, :high_confidence_eligible,
                        CAST(:hard_gate_status AS jsonb), CAST(:exclusion_reasons AS jsonb),
                        CAST(:penalty_summary AS jsonb), CAST(:component_summary AS jsonb),
                        CAST(:weight_config AS jsonb), :scored_at, 'smart_score_v1', :run_id
                    )
                    ON CONFLICT (wallet_address, score_version, scored_at) DO UPDATE SET
                        score = EXCLUDED.score,
                        raw_score = EXCLUDED.raw_score,
                        confidence = EXCLUDED.confidence,
                        high_confidence_eligible = EXCLUDED.high_confidence_eligible,
                        hard_gate_status = EXCLUDED.hard_gate_status,
                        exclusion_reasons = EXCLUDED.exclusion_reasons,
                        penalty_summary = EXCLUDED.penalty_summary,
                        component_summary = EXCLUDED.component_summary,
                        weight_config = EXCLUDED.weight_config,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {
                    "score_uid": result.score_uid,
                    "wallet_address": result.wallet_address,
                    "feature_uid": result.feature_uid,
                    "score_version": result.score_version,
                    "score": result.score,
                    "raw_score": result.raw_score,
                    "confidence": result.confidence,
                    "high_confidence_eligible": result.high_confidence_eligible,
                    "hard_gate_status": _json(result.hard_gate_status),
                    "exclusion_reasons": _json(result.exclusion_reasons),
                    "penalty_summary": _json(result.penalty_summary),
                    "component_summary": _json(result.component_summary),
                    "weight_config": _json(weight_config),
                    "scored_at": scored_at,
                    "run_id": run_id,
                },
            )
            self._upsert_score_components(result, run_id)
            count += 1
        return count

    def fetch_leaderboard(self, *, limit: int, high_confidence_only: bool = False) -> list[dict[str, Any]]:
        high_confidence_clause = "AND ws.high_confidence_eligible = true" if high_confidence_only else ""
        result = self.connection.execute(
            text(
                f"""
                SELECT
                    ws.wallet_address,
                    ws.score,
                    ws.confidence,
                    ws.high_confidence_eligible,
                    ws.exclusion_reasons,
                    ws.component_summary,
                    ws.scored_at,
                    wf.realized_pnl_180d,
                    wf.realized_notional_180d,
                    wf.net_roi_180d,
                    wf.n_resolved,
                    wf.active_days_180d,
                    wf.bayes_wr,
                    wf.max_drawdown_ratio,
                    wf.avg_followability,
                    wf.avg_clv_10m
                FROM wallet_scores ws
                JOIN wallet_features wf ON wf.feature_uid = ws.feature_uid
                WHERE ws.scored_at = (
                    SELECT max(scored_at) FROM wallet_scores
                )
                {high_confidence_clause}
                ORDER BY ws.score DESC, ws.confidence DESC, wf.realized_pnl_180d DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [dict(row._mapping) for row in result]

    def fetch_score_rows_for_backtest(self, *, scored_at: datetime, limit: int | None = None) -> list[dict[str, Any]]:
        limit_clause = "LIMIT :limit" if limit is not None else ""
        result = self.connection.execute(
            text(
                f"""
                SELECT
                    ws.wallet_address,
                    ws.score,
                    ws.confidence,
                    ws.high_confidence_eligible,
                    wf.realized_pnl_180d,
                    wf.net_roi_180d,
                    wf.active_days_180d,
                    to_jsonb(wf.*) AS feature_snapshot
                FROM wallet_scores ws
                JOIN wallet_features wf ON wf.feature_uid = ws.feature_uid
                WHERE ws.scored_at = :scored_at
                ORDER BY ws.score DESC, ws.confidence DESC
                {limit_clause}
                """
            ),
            {"scored_at": scored_at, "limit": limit},
        )
        return [dict(row._mapping) for row in result]

    def fetch_future_performance(
        self,
        *,
        wallet_addresses: Iterable[str],
        validation_start: datetime,
        validation_end: datetime,
    ) -> dict[str, dict[str, Any]]:
        addresses = list(dict.fromkeys(wallet_addresses))
        if not addresses:
            return {}
        result = self.connection.execute(
            text(
                """
                WITH future_results AS (
                    SELECT *
                    FROM wallet_market_results
                    WHERE wallet_address = ANY(:wallet_addresses)
                        AND COALESCE(exit_time, entry_time, calculated_at) > :validation_start
                        AND COALESCE(exit_time, entry_time, calculated_at) <= :validation_end
                ),
                pnl AS (
                    SELECT
                        wallet_address,
                        COALESCE(sum(realized_pnl), 0) AS future_realized_pnl,
                        COALESCE(sum(net_pnl), 0) AS future_net_pnl,
                        COALESCE(sum(capital_deployed), 0) AS future_capital_deployed
                    FROM future_results
                    GROUP BY wallet_address
                ),
                equity AS (
                    SELECT wallet_address, COALESCE(max(max_drawdown), 0) AS future_max_drawdown
                    FROM wallet_daily_equity
                    WHERE wallet_address = ANY(:wallet_addresses)
                        AND equity_date > :validation_start_date
                        AND equity_date <= :validation_end_date
                    GROUP BY wallet_address
                ),
                clv AS (
                    SELECT wallet_address, avg(clv_10m) AS future_avg_clv_10m
                    FROM trade_clv_metrics
                    WHERE wallet_address = ANY(:wallet_addresses)
                        AND trade_timestamp > :validation_start
                        AND trade_timestamp <= :validation_end
                    GROUP BY wallet_address
                )
                SELECT
                    addresses.wallet_address,
                    COALESCE(pnl.future_realized_pnl, 0) AS future_realized_pnl,
                    COALESCE(pnl.future_net_pnl, 0) AS future_net_pnl,
                    COALESCE(pnl.future_capital_deployed, 0) AS future_capital_deployed,
                    CASE WHEN COALESCE(pnl.future_capital_deployed, 0) = 0 THEN NULL
                        ELSE pnl.future_net_pnl / pnl.future_capital_deployed
                    END AS future_roi,
                    clv.future_avg_clv_10m,
                    COALESCE(equity.future_max_drawdown, 0) AS future_max_drawdown
                FROM unnest(:wallet_addresses) AS addresses(wallet_address)
                LEFT JOIN pnl ON pnl.wallet_address = addresses.wallet_address
                LEFT JOIN equity ON equity.wallet_address = addresses.wallet_address
                LEFT JOIN clv ON clv.wallet_address = addresses.wallet_address
                """
            ),
            {
                "wallet_addresses": addresses,
                "validation_start": validation_start,
                "validation_end": validation_end,
                "validation_start_date": validation_start.date(),
                "validation_end_date": validation_end.date(),
            },
        )
        return {str(row.wallet_address): dict(row._mapping) for row in result}

    def insert_backtest_run(
        self,
        *,
        backtest_run_uid: str,
        run_id: str,
        score_version: str,
        training_start: datetime,
        training_end: datetime,
        validation_start: datetime,
        validation_end: datetime,
        strategy_config: Mapping[str, Any],
        summary: Mapping[str, Any],
        status: str,
        started_at: datetime,
        finished_at: datetime | None,
    ) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO backtest_runs(
                    backtest_run_uid, score_version, training_start, training_end,
                    validation_start, validation_end, strategy_config, summary, status,
                    started_at, finished_at, source, ingestion_run_id
                )
                VALUES (
                    :backtest_run_uid, :score_version, :training_start, :training_end,
                    :validation_start, :validation_end, CAST(:strategy_config AS jsonb),
                    CAST(:summary AS jsonb), :status, :started_at, :finished_at,
                    'smart_score_v1', :run_id
                )
                ON CONFLICT (backtest_run_uid) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    status = EXCLUDED.status,
                    finished_at = EXCLUDED.finished_at,
                    updated_at = now()
                """
            ),
            {
                "backtest_run_uid": backtest_run_uid,
                "score_version": score_version,
                "training_start": training_start,
                "training_end": training_end,
                "validation_start": validation_start,
                "validation_end": validation_end,
                "strategy_config": _json(strategy_config),
                "summary": _json(summary),
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "run_id": run_id,
            },
        )

    def insert_backtest_wallet_results(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        backtest_run_uid: str,
        run_id: str,
    ) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                text(
                    """
                    INSERT INTO backtest_wallet_results(
                        result_uid, backtest_run_uid, wallet_address, strategy, strategy_rank,
                        training_score, training_confidence, training_features,
                        future_realized_pnl, future_net_pnl, future_capital_deployed,
                        future_roi, future_avg_clv_10m, future_max_drawdown, selected_at,
                        source, ingestion_run_id
                    )
                    VALUES (
                        :result_uid, :backtest_run_uid, :wallet_address, :strategy,
                        :strategy_rank, :training_score, :training_confidence,
                        CAST(:training_features AS jsonb), :future_realized_pnl,
                        :future_net_pnl, :future_capital_deployed, :future_roi,
                        :future_avg_clv_10m, :future_max_drawdown, :selected_at,
                        'smart_score_v1', :run_id
                    )
                    ON CONFLICT (result_uid) DO UPDATE SET
                        training_score = EXCLUDED.training_score,
                        training_confidence = EXCLUDED.training_confidence,
                        training_features = EXCLUDED.training_features,
                        future_realized_pnl = EXCLUDED.future_realized_pnl,
                        future_net_pnl = EXCLUDED.future_net_pnl,
                        future_capital_deployed = EXCLUDED.future_capital_deployed,
                        future_roi = EXCLUDED.future_roi,
                        future_avg_clv_10m = EXCLUDED.future_avg_clv_10m,
                        future_max_drawdown = EXCLUDED.future_max_drawdown,
                        updated_at = now()
                    """
                ),
                {
                    **row,
                    "backtest_run_uid": backtest_run_uid,
                    "run_id": run_id,
                    "training_features": _json(row.get("training_features", {})),
                },
            )
            count += 1
        return count

    def _upsert_score_components(self, result: SmartScoreResult, run_id: str) -> None:
        for component in result.components:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_score_components(
                        score_uid, component_name, component_score, max_score, details,
                        source, ingestion_run_id
                    )
                    VALUES (
                        :score_uid, :component_name, :component_score, :max_score,
                        CAST(:details AS jsonb), 'smart_score_v1', :run_id
                    )
                    ON CONFLICT (score_uid, component_name) DO UPDATE SET
                        component_score = EXCLUDED.component_score,
                        max_score = EXCLUDED.max_score,
                        details = EXCLUDED.details,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {
                    "score_uid": result.score_uid,
                    "component_name": component["component_name"],
                    "component_score": component["component_score"],
                    "max_score": component["max_score"],
                    "details": _json(component.get("details", {})),
                    "run_id": run_id,
                },
            )
