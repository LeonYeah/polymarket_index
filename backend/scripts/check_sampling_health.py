from __future__ import annotations

import argparse
import json

from backend.app.db.database import make_engine
from backend.app.db.paper_trading_repository import PaperTradingRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Check continuous sampling freshness and status.")
    parser.add_argument("--max-age-seconds", type=int, default=300)
    parser.add_argument("--allow-degraded", action="store_true")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    with make_engine(args.database_url).begin() as connection:
        health = PaperTradingRepository(connection).fetch_sampling_health(
            max_age_seconds=args.max_age_seconds
        )
    print(json.dumps(health, sort_keys=True, default=str))
    allowed = {"healthy", "degraded"} if args.allow_degraded else {"healthy"}
    if health["status"] not in allowed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
