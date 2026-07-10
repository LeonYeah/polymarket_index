from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from backend.app.analytics.paper_trading import (
    OrderType,
    Signal,
    StrategyConfig,
    build_signal,
    calculate_paper_pnl,
    merge_aligned_signals,
    simulate_order,
)
from backend.app.core.run_context import new_run_id
from backend.app.db.paper_trading_repository import PaperTradingRepository


@dataclass(frozen=True)
class PaperTradingRunResult:
    run_id: str
    status: str
    counters: dict[str, int]
    started_at: datetime
    finished_at: datetime


def run_paper_trading(
    engine: Engine,
    *,
    lookback_minutes: int = 60,
    signal_limit: int = 500,
    valuation_limit: int = 1000,
    order_type: OrderType = "FAK",
    config: StrategyConfig | None = None,
) -> PaperTradingRunResult:
    config = config or StrategyConfig()
    run_id = new_run_id("paper")
    started_at = datetime.now(UTC)
    counters = {
        "candidate_trades": 0,
        "signals": 0,
        "merged_signals": 0,
        "orders": 0,
        "rejected_orders": 0,
        "filled_orders": 0,
        "positions": 0,
        "expired_orders": 0,
        "pnl_valuations": 0,
    }
    params = {
        "lookback_minutes": lookback_minutes,
        "signal_limit": signal_limit,
        "valuation_limit": valuation_limit,
        "order_type": order_type,
        "strategy_version": config.strategy_version,
    }
    status = "completed"
    error: str | None = None
    with engine.begin() as connection:
        repository = PaperTradingRepository(connection)
        repository.start_run(run_id=run_id, started_at=started_at, params=params)
        try:
            with connection.begin_nested():
                _execute_cycle(
                    repository,
                    run_id=run_id,
                    started_at=started_at,
                    lookback_minutes=lookback_minutes,
                    signal_limit=signal_limit,
                    valuation_limit=valuation_limit,
                    order_type=order_type,
                    config=config,
                    counters=counters,
                )
        except Exception as exc:
            status = "failed"
            error = str(exc)
        finally:
            finished_at = datetime.now(UTC)
            repository.finish_run(
                run_id=run_id,
                status=status,
                finished_at=finished_at,
                counters=counters,
                error=error,
            )
    return PaperTradingRunResult(run_id, status, counters, started_at, finished_at)


def _execute_cycle(
    repository: PaperTradingRepository,
    *,
    run_id: str,
    started_at: datetime,
    lookback_minutes: int,
    signal_limit: int,
    valuation_limit: int,
    order_type: OrderType,
    config: StrategyConfig,
    counters: dict[str, int],
) -> None:
    counters["expired_orders"] = repository.expire_gtc_orders(
        expired_at=started_at,
        run_id=run_id,
    )
    rows = repository.fetch_signal_candidates(
        since=started_at - timedelta(minutes=lookback_minutes),
        limit=signal_limit,
    )
    counters["candidate_trades"] = len(rows)
    raw_signals = [build_signal(row, detected_at=started_at) for row in rows]
    for signal in raw_signals:
        counters["signals"] += repository.insert_signal(signal, run_id=run_id)
    actionable = _merge_signals(raw_signals, repository, run_id, counters)
    for signal in actionable:
        context, levels = repository.fetch_market_context(signal)
        decision_at = datetime.now(UTC)
        order = simulate_order(
            signal,
            context,
            levels,
            order_type=order_type,
            config=config,
            decision_at=decision_at,
            simulated_at=datetime.now(UTC),
        )
        inserted = repository.insert_order(order, run_id=run_id)
        counters["orders"] += inserted
        if inserted and order.status == "rejected":
            counters["rejected_orders"] += 1
        if inserted and order.status in {"would_fill", "would_partial_fill"}:
            counters["filled_orders"] += 1
            counters["positions"] += repository.upsert_position(order, run_id=run_id)

    valued_at = datetime.now(UTC)
    for row in repository.fetch_orders_for_valuation(limit=valuation_limit):
        pnl = calculate_paper_pnl(
            side=row["side"],
            entry_price=row["estimated_fill_price"],
            exit_price=row["exit_price"],
            filled_size=row["filled_size"],
            fee=row["estimated_fee"],
            leader_price=row["leader_price"],
        )
        counters["pnl_valuations"] += repository.insert_pnl(
            row,
            pnl,
            valued_at=valued_at,
            run_id=run_id,
        )


def _merge_signals(
    signals: list[Signal],
    repository: PaperTradingRepository,
    run_id: str,
    counters: dict[str, int],
) -> list[Signal]:
    grouped: dict[tuple[str, str, str, int], list[Signal]] = defaultdict(list)
    for signal in signals:
        five_minute_bucket = int(signal.leader_trade_time.timestamp()) // 300
        grouped[
            (signal.market_id, signal.token_id, signal.side, five_minute_bucket)
        ].append(signal)
    actionable: list[Signal] = []
    for rows in grouped.values():
        distinct_wallets = {row.leader_wallet for row in rows}
        if len(rows) > 1 and len(distinct_wallets) > 1:
            merged = merge_aligned_signals(rows)
            counters["merged_signals"] += repository.insert_signal(merged, run_id=run_id)
            repository.mark_signals_merged(
                (row.signal_id for row in rows),
                parent_id=merged.signal_id,
            )
            actionable.append(merged)
        else:
            actionable.extend(rows)
    return actionable
