from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine

from backend.app.analytics.smart_score import (
    FEATURE_VERSION,
    SMART_SCORE_VERSION,
    WEIGHT_CONFIG,
    select_backtest_strategies,
    score_wallet_features,
    stable_uid,
    summarize_backtest_results,
)
from backend.app.core.run_context import new_run_id
from backend.app.db.smart_score_repository import SmartScoreRepository


@dataclass(frozen=True)
class SmartScoreRunResult:
    run_id: str
    status: str
    counters: dict[str, int]
    started_at: datetime
    finished_at: datetime
    leaderboard: list[dict[str, Any]] = field(default_factory=list)
    backtest_summary: dict[str, Any] = field(default_factory=dict)


def run_smart_score(
    engine: Engine,
    *,
    wallet_limit: int | None = None,
    leaderboard_limit: int = 20,
    as_of: datetime | None = None,
    lookback_days: int = 180,
    high_confidence_only: bool = False,
    run_backtest: bool = False,
    validation_days: int = 30,
    strategy_size: int = 10,
) -> SmartScoreRunResult:
    run_id = new_run_id("smart_score")
    started_at = datetime.now(UTC)
    as_of = (as_of or started_at).astimezone(UTC)
    observation_start = as_of - timedelta(days=lookback_days)
    counters = {
        "feature_rows": 0,
        "scores": 0,
        "leaderboard_rows": 0,
        "backtest_wallet_results": 0,
    }
    params = {
        "wallet_limit": wallet_limit,
        "leaderboard_limit": leaderboard_limit,
        "as_of": as_of,
        "lookback_days": lookback_days,
        "high_confidence_only": high_confidence_only,
        "run_backtest": run_backtest,
        "validation_days": validation_days,
        "strategy_size": strategy_size,
    }
    status = "completed"
    error: str | None = None
    leaderboard: list[dict[str, Any]] = []
    backtest_summary: dict[str, Any] = {}
    with engine.begin() as connection:
        repository = SmartScoreRepository(connection)
        repository.start_run(run_id, "smart_score_v1", "polymarket", started_at, params)
        try:
            features = repository.fetch_feature_rows(
                run_id=run_id,
                feature_version=FEATURE_VERSION,
                as_of=as_of,
                observation_start=observation_start,
                wallet_limit=wallet_limit,
            )
            counters["feature_rows"] = repository.upsert_wallet_features(features, run_id)
            score_results = [
                score_wallet_features(feature, scored_at=as_of, score_version=SMART_SCORE_VERSION)
                for feature in features
            ]
            counters["scores"] = repository.upsert_wallet_scores(
                score_results,
                run_id=run_id,
                scored_at=as_of,
                weight_config=WEIGHT_CONFIG,
            )
            leaderboard = repository.fetch_leaderboard(
                limit=leaderboard_limit,
                high_confidence_only=high_confidence_only,
            )
            counters["leaderboard_rows"] = len(leaderboard)
            if run_backtest:
                rows, backtest_summary = _run_backtest(
                    repository,
                    run_id=run_id,
                    scored_at=as_of,
                    training_start=observation_start,
                    training_end=as_of,
                    validation_days=validation_days,
                    strategy_size=strategy_size,
                    wallet_limit=wallet_limit,
                )
                counters["backtest_wallet_results"] = rows
        except Exception as exc:
            status = "failed"
            error = str(exc)
            raise
        finally:
            finished_at = datetime.now(UTC)
            repository.finish_run(run_id, status, finished_at, counters, error=error)
    return SmartScoreRunResult(run_id, status, counters, started_at, finished_at, leaderboard, backtest_summary)


def _run_backtest(
    repository: SmartScoreRepository,
    *,
    run_id: str,
    scored_at: datetime,
    training_start: datetime,
    training_end: datetime,
    validation_days: int,
    strategy_size: int,
    wallet_limit: int | None,
) -> tuple[int, dict[str, Any]]:
    validation_start = training_end
    validation_end = validation_start + timedelta(days=validation_days)
    started_at = datetime.now(UTC)
    backtest_run_uid = stable_uid(
        ["backtest", SMART_SCORE_VERSION, training_start, training_end, validation_start, validation_end]
    )
    score_rows = repository.fetch_score_rows_for_backtest(scored_at=scored_at, limit=wallet_limit)
    selections = select_backtest_strategies(score_rows, top_n=strategy_size)
    future = repository.fetch_future_performance(
        wallet_addresses=[selection.wallet_address for selection in selections],
        validation_start=validation_start,
        validation_end=validation_end,
    )
    result_rows = []
    for selection in selections:
        future_row = future.get(selection.wallet_address, {})
        result_rows.append(
            {
                "result_uid": stable_uid(
                    [
                        "backtest_wallet_result",
                        backtest_run_uid,
                        selection.strategy,
                        selection.wallet_address,
                        selection.strategy_rank,
                    ]
                ),
                "wallet_address": selection.wallet_address,
                "strategy": selection.strategy,
                "strategy_rank": selection.strategy_rank,
                "training_score": selection.training_score,
                "training_confidence": selection.training_confidence,
                "training_features": selection.training_features,
                "future_realized_pnl": future_row.get("future_realized_pnl", 0),
                "future_net_pnl": future_row.get("future_net_pnl", 0),
                "future_capital_deployed": future_row.get("future_capital_deployed", 0),
                "future_roi": future_row.get("future_roi"),
                "future_avg_clv_10m": future_row.get("future_avg_clv_10m"),
                "future_max_drawdown": future_row.get("future_max_drawdown"),
                "selected_at": training_end,
            }
        )
    summary = summarize_backtest_results(result_rows)
    repository.insert_backtest_run(
        backtest_run_uid=backtest_run_uid,
        run_id=run_id,
        score_version=SMART_SCORE_VERSION,
        training_start=training_start,
        training_end=training_end,
        validation_start=validation_start,
        validation_end=validation_end,
        strategy_config={
            "strategies": ["top_score", "top_pnl", "random_active"],
            "strategy_size": strategy_size,
        },
        summary=summary,
        status="completed",
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    inserted = repository.insert_backtest_wallet_results(
        result_rows,
        backtest_run_uid=backtest_run_uid,
        run_id=run_id,
    )
    return inserted, summary
