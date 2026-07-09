from __future__ import annotations

import argparse
import json
from typing import Any

from backend.app.collectors.wallet_data import run_wallet_backfill_sync
from backend.app.core.config import get_settings
from backend.app.db.database import make_engine


def _json_default(value: Any) -> str:
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover candidate wallets and backfill read-only Polymarket wallet data."
    )
    parser.add_argument("--candidate-limit", type=int, default=None)
    parser.add_argument("--leaderboard-limit", type=int, default=None)
    parser.add_argument("--holder-candidate-limit", type=int, default=None)
    parser.add_argument("--active-trader-limit", type=int, default=None)
    parser.add_argument("--backfill-wallet-limit", type=int, default=None)
    parser.add_argument("--page-limit", type=int, default=None)
    parser.add_argument("--max-trade-pages", type=int, default=None)
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    settings = get_settings()
    engine = make_engine(args.database_url)
    result = run_wallet_backfill_sync(
        settings,
        engine,
        candidate_limit=args.candidate_limit,
        leaderboard_limit=args.leaderboard_limit,
        holder_candidate_limit=args.holder_candidate_limit,
        active_trader_limit=args.active_trader_limit,
        backfill_wallet_limit=args.backfill_wallet_limit,
        page_limit=args.page_limit,
        max_trade_pages=args.max_trade_pages,
    )
    print(json.dumps(result.__dict__, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
