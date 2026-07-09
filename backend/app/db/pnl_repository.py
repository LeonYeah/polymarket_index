from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from backend.app.analytics.pnl_engine import PnLInput


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class PnLRepository:
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

    def refresh_market_resolution_statuses(self, run_id: str) -> int:
        result = self.connection.execute(
            text(
                """
                INSERT INTO market_resolution_status(
                    condition_id, status, closed, active, archived, resolved_at, winning_outcome,
                    raw, source, ingestion_run_id
                )
                SELECT
                    condition_id,
                    CASE
                        WHEN archived THEN 'archived'
                        WHEN closed THEN 'closed'
                        WHEN active THEN 'open'
                        ELSE 'unknown'
                    END AS status,
                    closed,
                    active,
                    archived,
                    CASE WHEN closed THEN end_date ELSE NULL END AS resolved_at,
                    NULL AS winning_outcome,
                    raw,
                    'markets',
                    :run_id
                FROM markets
                ON CONFLICT (condition_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    closed = EXCLUDED.closed,
                    active = EXCLUDED.active,
                    archived = EXCLUDED.archived,
                    resolved_at = EXCLUDED.resolved_at,
                    raw = EXCLUDED.raw,
                    ingestion_run_id = EXCLUDED.ingestion_run_id,
                    updated_at = now()
                """
            ),
            {"run_id": run_id},
        )
        return int(result.rowcount or 0)

    def fetch_wallet_addresses(self, limit: int | None = None) -> list[str]:
        query = """
            SELECT wallet_address
            FROM (
                SELECT wallet_address, max(updated_at) AS updated_at FROM trades GROUP BY wallet_address
                UNION
                SELECT wallet_address, max(updated_at) AS updated_at
                FROM wallet_positions_current GROUP BY wallet_address
                UNION
                SELECT wallet_address, max(updated_at) AS updated_at
                FROM wallet_positions_closed GROUP BY wallet_address
            ) wallets_with_data
            ORDER BY updated_at DESC NULLS LAST, wallet_address
        """
        params: dict[str, Any] = {}
        if limit is not None:
            query += "\nLIMIT :limit"
            params["limit"] = limit
        result = self.connection.execute(text(query), params)
        return [str(row.wallet_address) for row in result]

    def fetch_wallet_input(self, wallet_address: str) -> PnLInput:
        trades = self._fetch_trades(wallet_address)
        current_positions = self._fetch_current_positions(wallet_address)
        closed_positions = self._fetch_closed_positions(wallet_address)
        condition_ids = {
            str(value)
            for value in [
                *(row.get("condition_id") for row in trades),
                *(row.get("condition_id") for row in current_positions),
                *(row.get("condition_id") for row in closed_positions),
            ]
            if value
        }
        return PnLInput(
            wallet_address=wallet_address,
            trades=trades,
            current_positions=current_positions,
            closed_positions=closed_positions,
            market_statuses=self._fetch_market_statuses(condition_ids),
        )

    def upsert_wallet_market_results(
        self, results: Iterable[Mapping[str, Any]], run_id: str
    ) -> int:
        count = 0
        for row in results:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_market_results(
                        result_uid, wallet_address, condition_id, token_id, outcome, market_status,
                        result_status, outcome_correct, trade_count, buy_count, sell_count,
                        taker_trade_count, total_buy_size, total_sell_size, total_buy_notional,
                        total_sell_notional, avg_buy_price, avg_sell_price, open_size,
                        capital_deployed, realized_pnl, unrealized_pnl, current_value,
                        estimated_fees, estimated_slippage, fees_estimated, slippage_estimated,
                        fee_risk_level, net_pnl, gross_roi, net_roi, entry_time, exit_time,
                        holding_duration_seconds, calculation_notes, calculated_at, source,
                        ingestion_run_id
                    )
                    VALUES (
                        :result_uid, :wallet_address, :condition_id, :token_id, :outcome,
                        :market_status, :result_status, :outcome_correct, :trade_count,
                        :buy_count, :sell_count, :taker_trade_count, :total_buy_size,
                        :total_sell_size, :total_buy_notional, :total_sell_notional,
                        :avg_buy_price, :avg_sell_price, :open_size, :capital_deployed,
                        :realized_pnl, :unrealized_pnl, :current_value, :estimated_fees,
                        :estimated_slippage, :fees_estimated, :slippage_estimated,
                        :fee_risk_level, :net_pnl, :gross_roi, :net_roi, :entry_time,
                        :exit_time, :holding_duration_seconds, CAST(:calculation_notes AS jsonb),
                        :calculated_at, :source, :run_id
                    )
                    ON CONFLICT (result_uid) DO UPDATE SET
                        market_status = EXCLUDED.market_status,
                        result_status = EXCLUDED.result_status,
                        outcome_correct = EXCLUDED.outcome_correct,
                        trade_count = EXCLUDED.trade_count,
                        buy_count = EXCLUDED.buy_count,
                        sell_count = EXCLUDED.sell_count,
                        taker_trade_count = EXCLUDED.taker_trade_count,
                        total_buy_size = EXCLUDED.total_buy_size,
                        total_sell_size = EXCLUDED.total_sell_size,
                        total_buy_notional = EXCLUDED.total_buy_notional,
                        total_sell_notional = EXCLUDED.total_sell_notional,
                        avg_buy_price = EXCLUDED.avg_buy_price,
                        avg_sell_price = EXCLUDED.avg_sell_price,
                        open_size = EXCLUDED.open_size,
                        capital_deployed = EXCLUDED.capital_deployed,
                        realized_pnl = EXCLUDED.realized_pnl,
                        unrealized_pnl = EXCLUDED.unrealized_pnl,
                        current_value = EXCLUDED.current_value,
                        estimated_fees = EXCLUDED.estimated_fees,
                        estimated_slippage = EXCLUDED.estimated_slippage,
                        fees_estimated = EXCLUDED.fees_estimated,
                        slippage_estimated = EXCLUDED.slippage_estimated,
                        fee_risk_level = EXCLUDED.fee_risk_level,
                        net_pnl = EXCLUDED.net_pnl,
                        gross_roi = EXCLUDED.gross_roi,
                        net_roi = EXCLUDED.net_roi,
                        entry_time = EXCLUDED.entry_time,
                        exit_time = EXCLUDED.exit_time,
                        holding_duration_seconds = EXCLUDED.holding_duration_seconds,
                        calculation_notes = EXCLUDED.calculation_notes,
                        calculated_at = EXCLUDED.calculated_at,
                        source = EXCLUDED.source,
                        ingestion_run_id = EXCLUDED.ingestion_run_id,
                        updated_at = now()
                    """
                ),
                {**row, "run_id": run_id, "calculation_notes": _json(row.get("calculation_notes", {}))},
            )
            count += 1
        return count

    def upsert_wallet_daily_equity(self, rows: Iterable[Mapping[str, Any]], run_id: str) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                text(
                    """
                    INSERT INTO wallet_daily_equity(
                        wallet_address, equity_date, realized_pnl_cumulative, unrealized_pnl,
                        net_pnl, capital_deployed, daily_volume, trades_count, drawdown,
                        max_drawdown, calculated_at, source, ingestion_run_id
                    )
                    VALUES (
                        :wallet_address, :equity_date, :realized_pnl_cumulative,
                        :unrealized_pnl, :net_pnl, :capital_deployed, :daily_volume,
                        :trades_count, :drawdown, :max_drawdown, :calculated_at, :source, :run_id
                    )
                    ON CONFLICT (wallet_address, equity_date) DO UPDATE SET
                        realized_pnl_cumulative = EXCLUDED.realized_pnl_cumulative,
                        unrealized_pnl = EXCLUDED.unrealized_pnl,
                        net_pnl = EXCLUDED.net_pnl,
                        capital_deployed = EXCLUDED.capital_deployed,
                        daily_volume = EXCLUDED.daily_volume,
                        trades_count = EXCLUDED.trades_count,
                        drawdown = EXCLUDED.drawdown,
                        max_drawdown = EXCLUDED.max_drawdown,
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

    def insert_reconciliation_checks(
        self, rows: Iterable[Mapping[str, Any]], run_id: str
    ) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                text(
                    """
                    INSERT INTO pnl_reconciliation_checks(
                        wallet_address, condition_id, token_id, check_type, status, diff_category,
                        engine_realized_pnl, source_realized_pnl, difference, tolerance, details,
                        checked_at, source, ingestion_run_id
                    )
                    VALUES (
                        :wallet_address, :condition_id, :token_id, :check_type, :status,
                        :diff_category, :engine_realized_pnl, :source_realized_pnl, :difference,
                        :tolerance, CAST(:details AS jsonb), :checked_at, :source, :run_id
                    )
                    """
                ),
                {**row, "run_id": run_id, "details": _json(row.get("details", {}))},
            )
            count += 1
        return count

    def fetch_wallet_profile(self, wallet_address: str) -> dict[str, Any] | None:
        result = self.connection.execute(
            text(
                """
                WITH result_stats AS (
                    SELECT
                        wallet_address,
                        count(*)::integer AS markets_count,
                        count(*) FILTER (WHERE result_status IN ('closed', 'settled'))::integer
                            AS closed_markets_count,
                        count(*) FILTER (WHERE result_status = 'open')::integer AS open_markets_count,
                        COALESCE(sum(realized_pnl), 0) AS realized_pnl,
                        COALESCE(sum(unrealized_pnl), 0) AS unrealized_pnl,
                        COALESCE(sum(net_pnl), 0) AS net_pnl,
                        COALESCE(sum(capital_deployed), 0) AS capital_deployed,
                        COALESCE(sum(realized_pnl) FILTER (WHERE realized_pnl > 0), 0) AS gross_profit,
                        abs(COALESCE(sum(realized_pnl) FILTER (WHERE realized_pnl < 0), 0)) AS gross_loss,
                        COALESCE(max(realized_pnl), 0) AS best_market_pnl,
                        count(*) FILTER (WHERE realized_pnl > 0)::integer AS wins_count,
                        count(*) FILTER (WHERE realized_pnl < 0)::integer AS losses_count
                    FROM wallet_market_results
                    WHERE wallet_address = :wallet_address
                    GROUP BY wallet_address
                ),
                equity_stats AS (
                    SELECT DISTINCT ON (wallet_address)
                        wallet_address,
                        max_drawdown
                    FROM wallet_daily_equity
                    WHERE wallet_address = :wallet_address
                    ORDER BY wallet_address, equity_date DESC
                )
                SELECT
                    rs.*,
                    CASE WHEN rs.capital_deployed = 0 THEN NULL
                        ELSE rs.net_pnl / rs.capital_deployed
                    END AS net_roi,
                    CASE WHEN rs.gross_loss = 0 THEN NULL
                        ELSE rs.gross_profit / rs.gross_loss
                    END AS profit_factor,
                    CASE WHEN (rs.wins_count + rs.losses_count) = 0 THEN NULL
                        ELSE rs.wins_count::numeric / (rs.wins_count + rs.losses_count)
                    END AS win_rate,
                    CASE WHEN rs.gross_profit = 0 THEN NULL
                        ELSE rs.best_market_pnl / rs.gross_profit
                    END AS single_market_profit_share,
                    COALESCE(es.max_drawdown, 0) AS max_drawdown
                FROM result_stats rs
                LEFT JOIN equity_stats es ON es.wallet_address = rs.wallet_address
                """
            ),
            {"wallet_address": wallet_address},
        ).one_or_none()
        return dict(result._mapping) if result else None

    def fetch_wallet_results(self, wallet_address: str, limit: int) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT *
                FROM wallet_market_results
                WHERE wallet_address = :wallet_address
                ORDER BY net_pnl DESC, calculated_at DESC
                LIMIT :limit
                """
            ),
            {"wallet_address": wallet_address, "limit": limit},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_trades(self, wallet_address: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    t.trade_uid,
                    t.wallet_address,
                    t.condition_id,
                    t.token_id,
                    mt.outcome,
                    t.side,
                    t.price,
                    t.size,
                    t.notional,
                    t.trade_timestamp,
                    t.taker_only,
                    t.raw
                FROM trades t
                LEFT JOIN market_tokens mt ON mt.token_id = t.token_id
                WHERE t.wallet_address = :wallet_address
                ORDER BY t.trade_timestamp ASC NULLS LAST, t.created_at ASC
                """
            ),
            {"wallet_address": wallet_address},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_current_positions(self, wallet_address: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    position_uid,
                    wallet_address,
                    condition_id,
                    token_id,
                    outcome,
                    size,
                    avg_price,
                    initial_value,
                    current_value,
                    cash_pnl,
                    realized_pnl,
                    cur_price,
                    snapshot_at
                FROM wallet_positions_current
                WHERE wallet_address = :wallet_address
                """
            ),
            {"wallet_address": wallet_address},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_closed_positions(self, wallet_address: str) -> list[dict[str, Any]]:
        result = self.connection.execute(
            text(
                """
                SELECT
                    position_uid,
                    wallet_address,
                    condition_id,
                    token_id,
                    outcome,
                    avg_price,
                    total_bought,
                    realized_pnl,
                    cur_price,
                    closed_at
                FROM wallet_positions_closed
                WHERE wallet_address = :wallet_address
                """
            ),
            {"wallet_address": wallet_address},
        )
        return [dict(row._mapping) for row in result]

    def _fetch_market_statuses(
        self, condition_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        ids = list(dict.fromkeys(condition_ids))
        if not ids:
            return {}
        result = self.connection.execute(
            text(
                """
                SELECT condition_id, status, closed, active, archived, resolved_at, winning_outcome
                FROM market_resolution_status
                WHERE condition_id = ANY(:condition_ids)
                """
            ),
            {"condition_ids": ids},
        )
        return {str(row.condition_id): dict(row._mapping) for row in result}
