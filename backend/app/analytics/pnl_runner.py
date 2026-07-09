from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Engine

from backend.app.analytics.pnl_engine import PnLRunResult, calculate_wallet_pnl
from backend.app.core.run_context import new_run_id
from backend.app.db.pnl_repository import PnLRepository


def run_pnl_calculation(
    engine: Engine,
    *,
    wallet_limit: int | None = None,
    reconciliation_limit: int = 30,
    profile_limit: int = 5,
) -> PnLRunResult:
    run_id = new_run_id("pnl_engine")
    started_at = datetime.now().astimezone()
    counters = {
        "wallets_processed": 0,
        "market_statuses_refreshed": 0,
        "wallet_market_results": 0,
        "wallet_daily_equity_rows": 0,
        "reconciliation_checks": 0,
        "failed_wallets": 0,
    }
    params = {
        "wallet_limit": wallet_limit,
        "reconciliation_limit": reconciliation_limit,
        "profile_limit": profile_limit,
    }
    wallet_profiles: list[dict[str, Any]] = []
    status = "completed"
    error: str | None = None
    finished_at = started_at
    with engine.begin() as connection:
        repository = PnLRepository(connection)
        repository.start_run(run_id, "pnl_engine_v1", "polymarket", started_at, params)
        try:
            counters["market_statuses_refreshed"] = repository.refresh_market_resolution_statuses(run_id)
            wallet_addresses = repository.fetch_wallet_addresses(wallet_limit)
            for wallet_address in wallet_addresses:
                try:
                    with connection.begin_nested():
                        pnl_input = repository.fetch_wallet_input(wallet_address)
                        result = calculate_wallet_pnl(
                            pnl_input,
                            run_id=run_id,
                            reconciliation_limit=reconciliation_limit,
                        )
                        counters["wallet_market_results"] += repository.upsert_wallet_market_results(
                            result.wallet_market_results, run_id
                        )
                        counters["wallet_daily_equity_rows"] += repository.upsert_wallet_daily_equity(
                            result.wallet_daily_equity, run_id
                        )
                        counters["reconciliation_checks"] += repository.insert_reconciliation_checks(
                            result.reconciliation_checks, run_id
                        )
                    counters["wallets_processed"] += 1
                except Exception:
                    counters["failed_wallets"] += 1
            for wallet_address in wallet_addresses[:profile_limit]:
                profile = repository.fetch_wallet_profile(wallet_address)
                if profile:
                    wallet_profiles.append(profile)
        except Exception as exc:
            status = "failed"
            error = str(exc)
            raise
        finally:
            finished_at = datetime.now().astimezone()
            repository.finish_run(run_id, status, finished_at, counters, error=error)
    return PnLRunResult(run_id, status, counters, started_at, finished_at, wallet_profiles)
