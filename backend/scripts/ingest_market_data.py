from __future__ import annotations

import argparse
import json
from typing import Any

from backend.app.collectors.market_data import run_market_ingestion_sync
from backend.app.core.config import get_settings
from backend.app.db.database import make_engine


def _json_default(value: Any) -> str:
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest read-only Polymarket market data.")
    parser.add_argument("--max-markets", type=int, default=None)
    parser.add_argument("--page-limit", type=int, default=None)
    parser.add_argument("--holders-market-limit", type=int, default=None)
    parser.add_argument("--holders-limit", type=int, default=None)
    parser.add_argument(
        "--categories",
        default=None,
        help="Comma-separated Gamma event categories to keep. Use empty string for all categories.",
    )
    parser.add_argument("--token-verification-limit", type=int, default=None)
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    settings = get_settings()
    engine = make_engine(args.database_url)
    result = run_market_ingestion_sync(
        settings,
        engine,
        max_markets=args.max_markets,
        page_limit=args.page_limit,
        holders_market_limit=args.holders_market_limit,
        holders_limit=args.holders_limit,
        categories=args.categories,
        token_verification_limit=args.token_verification_limit,
    )
    print(json.dumps(result.__dict__, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
