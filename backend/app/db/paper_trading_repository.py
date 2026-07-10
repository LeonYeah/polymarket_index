from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from backend.app.analytics.paper_trading import (
    BookLevel,
    MarketContext,
    PaperOrderDecision,
    PaperPnl,
    Signal,
    stable_uid,
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class PaperTradingRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def start_run(
        self,
        *,
        run_id: str,
        started_at: datetime,
        params: Mapping[str, Any],
    ) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO ingestion_runs(run_id, job_name, source, status, started_at, params)
                VALUES (:run_id, 'paper_trading', 'paper_trading_engine_v1', 'running',
                    :started_at, CAST(:params AS jsonb))
                ON CONFLICT (run_id) DO UPDATE SET
                    status = 'running', started_at = EXCLUDED.started_at,
                    params = EXCLUDED.params, updated_at = now()
                """
            ),
            {"run_id": run_id, "started_at": started_at, "params": _json(params)},
        )

    def finish_run(
        self,
        *,
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
                SET status = :status, finished_at = :finished_at,
                    counters = CAST(:counters AS jsonb), error = :error, updated_at = now()
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

    def fetch_signal_candidates(
        self,
        *,
        since: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                WITH latest_scores AS (
                    SELECT DISTINCT ON (wallet_address)
                        wallet_address, score, confidence, high_confidence_eligible,
                        component_summary, feature_uid
                    FROM wallet_scores
                    ORDER BY wallet_address, scored_at DESC
                )
                SELECT
                    t.trade_uid, t.wallet_address, t.condition_id, t.token_id, t.side,
                    t.price, t.size, t.trade_timestamp,
                    COALESCE(ls.score, 0) AS score,
                    COALESCE(ls.confidence, 0) AS confidence,
                    COALESCE(ls.high_confidence_eligible, false) AS high_confidence_eligible,
                    (ww.wallet_address IS NOT NULL) AS watchlisted,
                    COALESCE(wf.avg_followability, 0) AS followability,
                    COALESCE(wf.n_resolved, 0) AS n_resolved,
                    COALESCE(ls.confidence, 0) AS category_expertise,
                    LEAST(1, COALESCE(
                        1 - wf.max_drawdown_ratio,
                        ls.confidence,
                        0
                    )) AS recent_stability,
                    COALESCE(wf.avg_clv_10m, wf.avg_clv_2m, wf.avg_clv_30s)
                        AS expected_edge
                FROM trades t
                LEFT JOIN latest_scores ls ON ls.wallet_address = t.wallet_address
                LEFT JOIN wallet_features wf ON wf.feature_uid = ls.feature_uid
                LEFT JOIN watchlist_wallets ww
                    ON ww.wallet_address = t.wallet_address AND ww.status = 'active'
                LEFT JOIN signals s
                    ON s.source_trade_uid = t.trade_uid AND s.leader_wallet = t.wallet_address
                WHERE t.trade_timestamp >= :since
                    AND t.condition_id IS NOT NULL
                    AND t.token_id IS NOT NULL
                    AND upper(t.side) IN ('BUY', 'SELL')
                    AND t.price > 0
                    AND t.size > 0
                    AND s.signal_id IS NULL
                    AND (
                        ww.wallet_address IS NOT NULL
                        OR ls.high_confidence_eligible = true
                        OR (ls.score >= 60 AND ls.confidence >= 0.35)
                    )
                ORDER BY t.trade_timestamp, t.trade_uid
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
        return [dict(row._mapping) for row in rows]

    def insert_signal(self, signal: Signal, *, run_id: str) -> int:
        result = self.connection.execute(
            text(
                """
                INSERT INTO signals(
                    signal_id, source_trade_uid, leader_wallet, market_id, token_id, side,
                    leader_price, leader_size, leader_trade_time, detected_at, confidence,
                    wallet_weight, reason, evidence, processing_status, source,
                    ingestion_run_id
                )
                VALUES (
                    :signal_id, :source_trade_uid, :leader_wallet, :market_id, :token_id,
                    :side, :leader_price, :leader_size, :leader_trade_time, :detected_at,
                    :confidence, :wallet_weight, :reason, CAST(:evidence AS jsonb),
                    'pending', 'signal_engine_v1', :run_id
                )
                ON CONFLICT (signal_id) DO NOTHING
                """
            ),
            {
                **signal.__dict__,
                "evidence": _json({**signal.evidence, "merged_signal_ids": signal.merged_signal_ids}),
                "run_id": run_id,
            },
        )
        return int(result.rowcount or 0)

    def mark_signals_merged(self, child_ids: Iterable[str], *, parent_id: str) -> None:
        self.connection.execute(
            text(
                """
                UPDATE signals
                SET processing_status = 'merged', parent_signal_id = :parent_id,
                    updated_at = now()
                WHERE signal_id = ANY(:child_ids)
                """
            ),
            {"parent_id": parent_id, "child_ids": list(child_ids)},
        )

    def fetch_market_context(self, signal: Signal) -> tuple[MarketContext, list[BookLevel]]:
        row = self.connection.execute(
            text(
                """
                SELECT
                    m.accepting_orders, m.end_date,
                    ob.snapshot_uid, ob.snapshot_at, ob.midpoint, ob.spread_bps,
                    COALESCE(mfs.market_liquidity_score, 0) AS liquidity_score
                FROM markets m
                LEFT JOIN LATERAL (
                    SELECT * FROM orderbook_top
                    WHERE asset_id = :token_id
                    ORDER BY snapshot_at DESC LIMIT 1
                ) ob ON true
                LEFT JOIN market_followability_snapshots mfs
                    ON mfs.snapshot_uid = ob.snapshot_uid
                WHERE m.condition_id = :market_id
                LIMIT 1
                """
            ),
            {"token_id": signal.token_id, "market_id": signal.market_id},
        ).one_or_none()
        if row is None:
            return (
                MarketContext(
                    accepting_orders=False,
                    end_date=None,
                    snapshot_at=None,
                    liquidity_score=Decimal("0"),
                    spread_bps=None,
                    midpoint=None,
                ),
                [],
            )
        context = MarketContext(
            accepting_orders=bool(row.accepting_orders),
            end_date=row.end_date,
            snapshot_at=row.snapshot_at,
            liquidity_score=Decimal(str(row.liquidity_score)),
            spread_bps=Decimal(str(row.spread_bps)) if row.spread_bps is not None else None,
            midpoint=Decimal(str(row.midpoint)) if row.midpoint is not None else None,
            snapshot_uid=row.snapshot_uid,
        )
        if row.snapshot_uid is None:
            return context, []
        book_side = "ask" if signal.side == "BUY" else "bid"
        level_rows = self.connection.execute(
            text(
                """
                SELECT price, size
                FROM orderbook_depth_snapshots
                WHERE snapshot_uid = :snapshot_uid AND side = :book_side
                ORDER BY level_index
                """
            ),
            {"snapshot_uid": row.snapshot_uid, "book_side": book_side},
        )
        return context, [
            BookLevel(price=Decimal(str(level.price)), size=Decimal(str(level.size)))
            for level in level_rows
        ]

    def insert_order(self, order: PaperOrderDecision, *, run_id: str) -> int:
        result = self.connection.execute(
            text(
                """
                INSERT INTO paper_orders(
                    order_id, signal_id, strategy_version, order_type, side, market_id,
                    token_id, requested_size, requested_notional, worst_price,
                    estimated_fill_price, filled_size, estimated_slippage, estimated_fee,
                    status, reject_reason, leader_trade_time, signal_detected_at,
                    decision_at, order_simulated_at, detection_latency_ms,
                    decision_latency_ms, simulation_latency_ms, orderbook_snapshot_uid,
                    decision_evidence, source, ingestion_run_id
                )
                VALUES (
                    :order_id, :signal_id, :strategy_version, :order_type, :side,
                    :market_id, :token_id, :requested_size, :requested_notional,
                    :worst_price, :estimated_fill_price, :filled_size,
                    :estimated_slippage, :estimated_fee, :status, :reject_reason,
                    :leader_trade_time, :signal_detected_at, :decision_at,
                    :order_simulated_at, :detection_latency_ms, :decision_latency_ms,
                    :simulation_latency_ms, :orderbook_snapshot_uid,
                    CAST(:evidence AS jsonb), 'paper_trading_engine_v1', :run_id
                )
                ON CONFLICT (signal_id, strategy_version, order_type) DO NOTHING
                """
            ),
            {**order.__dict__, "evidence": _json(order.evidence), "run_id": run_id},
        )
        if result.rowcount:
            self.connection.execute(
                text(
                    """
                    INSERT INTO paper_order_events(
                        event_id, order_id, from_status, to_status, event_at, reason,
                        details, ingestion_run_id
                    )
                    VALUES (:event_id, :order_id, NULL, :status, :event_at, :reason,
                        CAST(:details AS jsonb), :run_id)
                    ON CONFLICT (event_id) DO NOTHING
                    """
                ),
                {
                    "event_id": stable_uid(["paper_order_event", order.order_id, order.status]),
                    "order_id": order.order_id,
                    "status": order.status,
                    "event_at": order.order_simulated_at,
                    "reason": order.reject_reason,
                    "details": _json(order.evidence),
                    "run_id": run_id,
                },
            )
            self.connection.execute(
                text(
                    """
                    UPDATE signals SET processing_status = :processing_status, updated_at = now()
                    WHERE signal_id = :signal_id
                    """
                ),
                {
                    "processing_status": (
                        "rejected" if order.status == "rejected" else "ordered"
                    ),
                    "signal_id": order.signal_id,
                },
            )
        return int(result.rowcount or 0)

    def expire_gtc_orders(self, *, expired_at: datetime, run_id: str) -> int:
        rows = self.connection.execute(
            text(
                """
                UPDATE paper_orders
                SET status = 'expired', updated_at = now()
                WHERE order_type = 'GTC' AND status = 'created'
                    AND order_simulated_at < :expired_at - interval '10 minutes'
                RETURNING order_id
                """
            ),
            {"expired_at": expired_at},
        )
        order_ids = [str(row.order_id) for row in rows]
        for order_id in order_ids:
            self.connection.execute(
                text(
                    """
                    INSERT INTO paper_order_events(
                        event_id, order_id, from_status, to_status, event_at,
                        reason, details, ingestion_run_id
                    )
                    VALUES (:event_id, :order_id, 'created', 'expired', :event_at,
                        'gtc_time_to_live_elapsed', '{}'::jsonb, :run_id)
                    ON CONFLICT (event_id) DO NOTHING
                    """
                ),
                {
                    "event_id": stable_uid(["paper_order_event", order_id, "expired"]),
                    "order_id": order_id,
                    "event_at": expired_at,
                    "run_id": run_id,
                },
            )
        return len(order_ids)

    def upsert_position(self, order: PaperOrderDecision, *, run_id: str) -> int:
        if order.filled_size <= 0 or order.estimated_fill_price is None:
            return 0
        position_id = stable_uid(
            ["paper_position", order.strategy_version, order.market_id, order.token_id, order.side]
        )
        result = self.connection.execute(
            text(
                """
                INSERT INTO paper_positions(
                    position_id, strategy_version, market_id, token_id, side, size,
                    average_entry_price, cost_basis, accumulated_fee, status,
                    opened_at, updated_at, source, ingestion_run_id
                )
                VALUES (
                    :position_id, :strategy_version, :market_id, :token_id, :side,
                    :size, :average_entry_price, :cost_basis, :fee, 'open',
                    :opened_at, :opened_at, 'paper_trading_engine_v1', :run_id
                )
                ON CONFLICT (strategy_version, market_id, token_id, side) DO UPDATE SET
                    average_entry_price = (
                        paper_positions.cost_basis + EXCLUDED.cost_basis
                    ) / NULLIF(paper_positions.size + EXCLUDED.size, 0),
                    size = paper_positions.size + EXCLUDED.size,
                    cost_basis = paper_positions.cost_basis + EXCLUDED.cost_basis,
                    accumulated_fee = paper_positions.accumulated_fee + EXCLUDED.accumulated_fee,
                    updated_at = EXCLUDED.updated_at,
                    ingestion_run_id = EXCLUDED.ingestion_run_id
                """
            ),
            {
                "position_id": position_id,
                "strategy_version": order.strategy_version,
                "market_id": order.market_id,
                "token_id": order.token_id,
                "side": order.side,
                "size": order.filled_size,
                "average_entry_price": order.estimated_fill_price,
                "cost_basis": order.estimated_fill_price * order.filled_size,
                "fee": order.estimated_fee,
                "opened_at": order.order_simulated_at,
                "run_id": run_id,
            },
        )
        return int(result.rowcount or 0)

    def fetch_orders_for_valuation(self, *, limit: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT
                    po.*, s.leader_price,
                    COALESCE(
                        CASE
                            WHEN mrs.status IN ('settled', 'resolved')
                                AND mt.outcome = mrs.winning_outcome THEN 1
                            WHEN mrs.status IN ('settled', 'resolved') THEN 0
                            ELSE ob.midpoint
                        END,
                        po.estimated_fill_price
                    ) AS exit_price,
                    CASE WHEN mrs.status IN ('settled', 'resolved')
                        THEN 'settled' ELSE 'mark_to_market' END AS valuation_type
                FROM paper_orders po
                JOIN signals s ON s.signal_id = po.signal_id
                LEFT JOIN market_tokens mt ON mt.token_id = po.token_id
                LEFT JOIN market_resolution_status mrs ON mrs.condition_id = po.market_id
                LEFT JOIN LATERAL (
                    SELECT midpoint FROM orderbook_top
                    WHERE asset_id = po.token_id AND midpoint IS NOT NULL
                    ORDER BY snapshot_at DESC LIMIT 1
                ) ob ON true
                WHERE po.status IN ('would_fill', 'would_partial_fill')
                    AND po.filled_size > 0
                ORDER BY po.order_simulated_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [dict(row._mapping) for row in rows]

    def insert_pnl(
        self,
        row: Mapping[str, Any],
        pnl: PaperPnl,
        *,
        valued_at: datetime,
        run_id: str,
    ) -> int:
        pnl_id = stable_uid(["paper_pnl", row["order_id"], row["valuation_type"], valued_at])
        result = self.connection.execute(
            text(
                """
                INSERT INTO paper_pnl(
                    pnl_id, order_id, strategy_version, market_id, token_id,
                    valuation_type, entry_price, exit_price, filled_size, gross_pnl,
                    fee, slippage_cost, net_pnl, direction_correct,
                    profitable_after_costs, valued_at, attribution, ingestion_run_id
                )
                VALUES (
                    :pnl_id, :order_id, :strategy_version, :market_id, :token_id,
                    :valuation_type, :entry_price, :exit_price, :filled_size,
                    :gross_pnl, :fee, :slippage_cost, :net_pnl, :direction_correct,
                    :profitable_after_costs, :valued_at, CAST(:attribution AS jsonb), :run_id
                )
                ON CONFLICT (order_id, valuation_type, valued_at) DO NOTHING
                """
            ),
            {
                "pnl_id": pnl_id,
                "order_id": row["order_id"],
                "strategy_version": row["strategy_version"],
                "market_id": row["market_id"],
                "token_id": row["token_id"],
                "valuation_type": row["valuation_type"],
                "entry_price": row["estimated_fill_price"],
                "exit_price": row["exit_price"],
                "filled_size": row["filled_size"],
                **pnl.__dict__,
                "valued_at": valued_at,
                "attribution": _json(
                    {
                        "direction_correct_but_unprofitable": (
                            pnl.direction_correct and not pnl.profitable_after_costs
                        ),
                        "leader_price": row["leader_price"],
                    }
                ),
                "run_id": run_id,
            },
        )
        if row["valuation_type"] == "settled":
            self._settle_order(str(row["order_id"]), valued_at, run_id)
        return int(result.rowcount or 0)

    def _settle_order(self, order_id: str, settled_at: datetime, run_id: str) -> None:
        previous_status = self.connection.execute(
            text("SELECT status FROM paper_orders WHERE order_id = :order_id"),
            {"order_id": order_id},
        ).scalar_one_or_none()
        changed = self.connection.execute(
            text(
                """
                UPDATE paper_orders SET status = 'settled', updated_at = now()
                WHERE order_id = :order_id AND status <> 'settled'
                RETURNING order_id
                """
            ),
            {"order_id": order_id},
        ).one_or_none()
        if changed:
            self.connection.execute(
                text(
                    """
                    UPDATE paper_positions pp
                    SET status = 'settled', settled_at = :settled_at,
                        updated_at = :settled_at, ingestion_run_id = :run_id
                    FROM paper_orders po
                    WHERE po.order_id = :order_id
                        AND pp.strategy_version = po.strategy_version
                        AND pp.market_id = po.market_id
                        AND pp.token_id = po.token_id
                        AND pp.side = po.side
                    """
                ),
                {"settled_at": settled_at, "run_id": run_id, "order_id": order_id},
            )
            self.connection.execute(
                text(
                    """
                    INSERT INTO paper_order_events(
                        event_id, order_id, from_status, to_status, event_at,
                        reason, details, ingestion_run_id
                    )
                    VALUES (:event_id, :order_id, :from_status, 'settled', :event_at,
                        'market_resolved', '{}'::jsonb, :run_id)
                    ON CONFLICT (event_id) DO NOTHING
                    """
                ),
                {
                    "event_id": stable_uid(["paper_order_event", order_id, "settled"]),
                    "order_id": order_id,
                    "from_status": previous_status,
                    "event_at": settled_at,
                    "run_id": run_id,
                },
            )

    def fetch_signals(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT s.*, po.order_id, po.status AS order_status, po.reject_reason
                FROM signals s
                LEFT JOIN paper_orders po ON po.signal_id = s.signal_id
                ORDER BY s.detected_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
        return [dict(row._mapping) for row in rows]

    def count_signals(self) -> int:
        return int(self.connection.execute(text("SELECT count(*) FROM signals")).scalar_one())

    def fetch_orders(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT po.*, s.leader_wallet, s.reason AS signal_reason, pp.net_pnl,
                    pp.direction_correct, pp.profitable_after_costs, pp.valued_at
                FROM paper_orders po
                JOIN signals s ON s.signal_id = po.signal_id
                LEFT JOIN LATERAL (
                    SELECT * FROM paper_pnl
                    WHERE order_id = po.order_id
                    ORDER BY valued_at DESC LIMIT 1
                ) pp ON true
                ORDER BY po.order_simulated_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
        return [dict(row._mapping) for row in rows]

    def count_orders(self) -> int:
        return int(self.connection.execute(text("SELECT count(*) FROM paper_orders")).scalar_one())

    def fetch_summary(self) -> dict[str, Any]:
        strategy = self.connection.execute(
            text(
                """
                WITH latest_pnl AS (
                    SELECT DISTINCT ON (order_id) *
                    FROM paper_pnl ORDER BY order_id, valued_at DESC
                ), equity AS (
                    SELECT valued_at, sum(net_pnl) OVER (ORDER BY valued_at) AS cumulative_pnl
                    FROM latest_pnl
                ), drawdown AS (
                    SELECT cumulative_pnl,
                        GREATEST(0, max(cumulative_pnl) OVER (ORDER BY valued_at))
                            - cumulative_pnl AS drawdown
                    FROM equity
                )
                SELECT
                    count(*)::integer AS valued_orders,
                    COALESCE(sum(lp.net_pnl), 0) AS net_pnl,
                    COALESCE(sum(po.estimated_fill_price * po.filled_size), 0)
                        AS capital_deployed,
                    CASE WHEN COALESCE(sum(po.estimated_fill_price * po.filled_size), 0) = 0
                        THEN NULL ELSE sum(lp.net_pnl)
                            / sum(po.estimated_fill_price * po.filled_size) END AS net_roi,
                    avg(CASE WHEN lp.net_pnl > 0 THEN 1 ELSE 0 END) AS win_rate,
                    COALESCE((SELECT max(drawdown) FROM drawdown), 0) AS max_drawdown,
                    count(*) FILTER (
                        WHERE lp.direction_correct AND NOT lp.profitable_after_costs
                    )::integer AS direction_correct_but_unprofitable
                FROM latest_pnl lp
                JOIN paper_orders po ON po.order_id = lp.order_id
                """
            )
        ).one()
        statuses = self.connection.execute(
            text("SELECT status, count(*)::integer AS count FROM paper_orders GROUP BY status")
        )
        rejects = self.connection.execute(
            text(
                """
                SELECT reject_reason, count(*)::integer AS count
                FROM paper_orders WHERE reject_reason IS NOT NULL
                GROUP BY reject_reason ORDER BY count DESC, reject_reason
                """
            )
        )
        runtime = self.connection.execute(
            text(
                """
                SELECT min(started_at) AS first_run_at, max(finished_at) AS last_run_at,
                    count(*)::integer AS run_count,
                    count(*) FILTER (WHERE status = 'failed')::integer AS failed_runs
                FROM ingestion_runs WHERE job_name = 'paper_trading'
                """
            )
        ).one()
        return {
            "strategy": dict(strategy._mapping),
            "order_status_distribution": {row.status: row.count for row in statuses},
            "reject_distribution": {row.reject_reason: row.count for row in rejects},
            "runtime": dict(runtime._mapping),
        }
