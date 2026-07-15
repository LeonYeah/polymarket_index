from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine

from backend.app.analytics.paper_trading import StrategyConfig
from backend.app.analytics.paper_trading_runner import run_paper_trading
from backend.app.collectors.incremental_wallet_data import run_incremental_wallet_sync
from backend.app.collectors.price_data import run_price_archive_sync
from backend.app.core.config import Settings
from backend.app.core.run_context import new_run_id
from backend.app.db.wallet_repository import WalletDataRepository


@dataclass(frozen=True)
class ContinuousSamplingResult:
    run_id: str
    status: str
    counters: dict[str, Any]
    started_at: datetime
    finished_at: datetime
    errors: dict[str, str] = field(default_factory=dict)


def run_continuous_sampling_cycle(
    settings: Settings,
    engine: Engine,
    *,
    research_wallet_limit: int = 25,
    trade_page_limit: int = 100,
    trade_max_pages: int = 2,
    token_limit: int = 30,
    token_recent_hours: int = 168,
    paper_lookback_minutes: int = 120,
) -> ContinuousSamplingResult:
    run_id = new_run_id("sampling")
    started_at = datetime.now(UTC)
    params = {
        "research_wallet_limit": research_wallet_limit,
        "trade_page_limit": trade_page_limit,
        "trade_max_pages": trade_max_pages,
        "token_limit": token_limit,
        "token_recent_hours": token_recent_hours,
        "paper_lookback_minutes": paper_lookback_minutes,
    }
    counters: dict[str, Any] = {"target_tokens": 0}
    errors: dict[str, str] = {}
    _record_cycle_start(engine, run_id, started_at, params)

    try:
        wallet_result = run_incremental_wallet_sync(
            settings,
            engine,
            research_wallet_limit=research_wallet_limit,
            page_limit=trade_page_limit,
            max_pages=trade_max_pages,
        )
        counters["wallet_incremental"] = wallet_result.counters
        if wallet_result.status not in {"succeeded", "completed"}:
            errors["wallet_incremental"] = wallet_result.status
    except Exception as exc:  # noqa: BLE001 - continue with cached DB state.
        errors["wallet_incremental"] = f"{type(exc).__name__}: {exc}"

    try:
        with engine.begin() as connection:
            tokens = WalletDataRepository(connection).fetch_sampling_token_ids(
                limit=token_limit,
                recent_hours=token_recent_hours,
                research_wallet_limit=research_wallet_limit,
            )
        counters["target_tokens"] = len(tokens)
        if tokens:
            price_result = run_price_archive_sync(
                settings,
                engine,
                token_ids=tokens,
                token_limit=token_limit,
                include_price_history=False,
                include_orderbook=True,
                include_websocket=False,
                include_clv=False,
                orderbook_cycles=1,
            )
            counters["price_archive"] = price_result.counters
            if price_result.status not in {"succeeded", "completed"}:
                errors["price_archive"] = price_result.status
        else:
            errors["price_archive"] = "no_target_tokens"
    except Exception as exc:  # noqa: BLE001 - paper engine should still explain stale data.
        errors["price_archive"] = f"{type(exc).__name__}: {exc}"

    try:
        paper_result = run_paper_trading(
            engine,
            lookback_minutes=paper_lookback_minutes,
            signal_limit=500,
            valuation_limit=1000,
            order_type="FAK",
            config=StrategyConfig(
                maximum_token_notional=settings.paper_maximum_token_notional,
            ),
        )
        counters["paper_trading"] = paper_result.counters
        if paper_result.status != "completed":
            errors["paper_trading"] = paper_result.status
    except Exception as exc:  # noqa: BLE001 - record the cycle and let the service retry.
        errors["paper_trading"] = f"{type(exc).__name__}: {exc}"

    finished_at = datetime.now(UTC)
    status = "succeeded" if not errors else "degraded"
    _record_cycle_finish(engine, run_id, status, finished_at, counters, errors)
    return ContinuousSamplingResult(
        run_id,
        status,
        counters,
        started_at,
        finished_at,
        errors,
    )


def _record_cycle_start(
    engine: Engine,
    run_id: str,
    started_at: datetime,
    params: dict[str, Any],
) -> None:
    with engine.begin() as connection:
        WalletDataRepository(connection).start_run(
            run_id,
            "continuous_sampling_cycle",
            "polymarket",
            started_at,
            params,
        )


def _record_cycle_finish(
    engine: Engine,
    run_id: str,
    status: str,
    finished_at: datetime,
    counters: dict[str, Any],
    errors: dict[str, str],
) -> None:
    with engine.begin() as connection:
        WalletDataRepository(connection).finish_run(
            run_id,
            status,
            finished_at,
            counters,
            None if not errors else str(errors),
        )
