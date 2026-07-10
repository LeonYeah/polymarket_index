from __future__ import annotations

import argparse
import json
from typing import Any

from backend.app.analytics.pnl_runner import run_pnl_calculation
from backend.app.analytics.smart_score_runner import run_smart_score
from backend.app.collectors.market_data import run_market_ingestion_sync
from backend.app.core.config import get_settings
from backend.app.db.database import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh market metadata, wallet PnL, and SmartScore for sampling."
    )
    parser.add_argument("--max-markets", type=int, default=500)
    parser.add_argument("--wallet-limit", type=int, default=150)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(args.database_url)
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    try:
        market = run_market_ingestion_sync(
            settings,
            engine,
            max_markets=args.max_markets,
            page_limit=100,
            holders_market_limit=5,
            holders_limit=20,
            categories="",
            token_verification_limit=50,
        )
        results["market_ingestion"] = market.__dict__
    except Exception as exc:  # noqa: BLE001 - later analytics can use the previous snapshot.
        errors["market_ingestion"] = f"{type(exc).__name__}: {exc}"
    try:
        pnl = run_pnl_calculation(
            engine,
            wallet_limit=args.wallet_limit,
            reconciliation_limit=30,
            profile_limit=5,
        )
        results["pnl"] = pnl.__dict__
    except Exception as exc:  # noqa: BLE001 - scoring may still refresh from prior PnL.
        errors["pnl"] = f"{type(exc).__name__}: {exc}"
    try:
        score = run_smart_score(
            engine,
            wallet_limit=args.wallet_limit,
            leaderboard_limit=100,
            run_backtest=False,
        )
        results["smart_score"] = score.__dict__
    except Exception as exc:  # noqa: BLE001 - report all maintenance stages together.
        errors["smart_score"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps({"results": results, "errors": errors}, sort_keys=True, default=str))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
