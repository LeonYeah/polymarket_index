from __future__ import annotations

import argparse
import json
from typing import Any

from backend.app.analytics.pnl_runner import run_pnl_calculation
from backend.app.analytics.smart_score_runner import run_smart_score
from backend.app.collectors.market_data import run_market_ingestion_sync
from backend.app.collectors.price_data import run_price_archive_sync
from backend.app.collectors.wallet_data import run_wallet_backfill_sync
from backend.app.core.config import get_settings
from backend.app.db.database import make_engine
from backend.app.db.wallet_repository import WalletDataRepository


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh market metadata, discover candidate wallets, backfill a bounded batch, "
            "materialize mature CLV horizons, and update PnL and SmartScore."
        )
    )
    parser.add_argument("--max-markets", type=int, default=500)
    parser.add_argument("--wallet-limit", type=int, default=150)
    parser.add_argument("--discovery-candidate-limit", type=int, default=500)
    parser.add_argument("--discovery-leaderboard-limit", type=int, default=150)
    parser.add_argument("--discovery-holder-limit", type=int, default=250)
    parser.add_argument("--discovery-active-trader-limit", type=int, default=250)
    parser.add_argument("--discovery-backfill-wallet-limit", type=int, default=25)
    parser.add_argument("--discovery-page-limit", type=int, default=100)
    parser.add_argument("--discovery-max-trade-pages", type=int, default=2)
    parser.add_argument("--clv-limit", type=int, default=1000)
    parser.add_argument("--research-wallet-limit", type=int, default=25)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(args.database_url)
    results, errors = run_sampling_maintenance(
        settings,
        engine,
        max_markets=args.max_markets,
        wallet_limit=args.wallet_limit,
        discovery_candidate_limit=args.discovery_candidate_limit,
        discovery_leaderboard_limit=args.discovery_leaderboard_limit,
        discovery_holder_limit=args.discovery_holder_limit,
        discovery_active_trader_limit=args.discovery_active_trader_limit,
        discovery_backfill_wallet_limit=args.discovery_backfill_wallet_limit,
        discovery_page_limit=args.discovery_page_limit,
        discovery_max_trade_pages=args.discovery_max_trade_pages,
        clv_limit=args.clv_limit,
        research_wallet_limit=args.research_wallet_limit,
    )
    print(json.dumps({"results": results, "errors": errors}, sort_keys=True, default=str))
    if errors:
        raise SystemExit(1)


def run_sampling_maintenance(
    settings: Any,
    engine: Any,
    *,
    max_markets: int = 500,
    wallet_limit: int = 150,
    discovery_candidate_limit: int = 500,
    discovery_leaderboard_limit: int = 150,
    discovery_holder_limit: int = 250,
    discovery_active_trader_limit: int = 250,
    discovery_backfill_wallet_limit: int = 25,
    discovery_page_limit: int = 100,
    discovery_max_trade_pages: int = 2,
    clv_limit: int = 1000,
    research_wallet_limit: int = 25,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run independent maintenance stages while preserving later-stage progress."""
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    try:
        market = run_market_ingestion_sync(
            settings,
            engine,
            max_markets=max_markets,
            page_limit=100,
            holders_market_limit=5,
            holders_limit=20,
            categories="",
            token_verification_limit=50,
        )
        results["market_ingestion"] = _compact_result(market)
    except Exception as exc:  # noqa: BLE001 - later analytics can use the previous snapshot.
        errors["market_ingestion"] = f"{type(exc).__name__}: {exc}"
    try:
        discovery = run_wallet_backfill_sync(
            settings,
            engine,
            candidate_limit=discovery_candidate_limit,
            leaderboard_limit=discovery_leaderboard_limit,
            holder_candidate_limit=discovery_holder_limit,
            active_trader_limit=discovery_active_trader_limit,
            backfill_wallet_limit=discovery_backfill_wallet_limit,
            page_limit=discovery_page_limit,
            max_trade_pages=discovery_max_trade_pages,
        )
        results["wallet_discovery"] = _compact_result(discovery)
    except Exception as exc:  # noqa: BLE001 - analytics can use the previous candidate snapshot.
        errors["wallet_discovery"] = f"{type(exc).__name__}: {exc}"
    try:
        with engine.begin() as connection:
            sampling_wallets = WalletDataRepository(connection).fetch_sampling_wallets(
                research_wallet_limit
            )
        clv_wallet_addresses = [str(row["wallet_address"]) for row in sampling_wallets]
        clv = run_price_archive_sync(
            settings,
            engine,
            token_ids=[],
            token_limit=0,
            include_price_history=False,
            include_orderbook=False,
            include_websocket=False,
            include_clv=True,
            clv_limit=clv_limit,
            clv_wallet_addresses=clv_wallet_addresses,
        )
        results["clv"] = _compact_result(clv)
    except Exception as exc:  # noqa: BLE001 - PnL and scores can use prior CLV rows.
        errors["clv"] = f"{type(exc).__name__}: {exc}"
    try:
        pnl = run_pnl_calculation(
            engine,
            wallet_limit=wallet_limit,
            reconciliation_limit=30,
            profile_limit=5,
        )
        results["pnl"] = _compact_result(pnl)
    except Exception as exc:  # noqa: BLE001 - scoring may still refresh from prior PnL.
        errors["pnl"] = f"{type(exc).__name__}: {exc}"
    try:
        score = run_smart_score(
            engine,
            wallet_limit=wallet_limit,
            leaderboard_limit=100,
            run_backtest=False,
        )
        results["smart_score"] = _compact_result(score)
    except Exception as exc:  # noqa: BLE001 - report all maintenance stages together.
        errors["smart_score"] = f"{type(exc).__name__}: {exc}"
    return results, errors


def _compact_result(result: Any) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "counters": result.counters,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
    }


if __name__ == "__main__":
    main()
