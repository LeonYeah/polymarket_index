from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from backend.app.analytics.smart_score_runner import run_smart_score
from backend.app.db.database import make_engine


def _json_default(value: Any) -> str:
    return str(value)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    return datetime.fromisoformat(candidate)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SmartScore wallet rankings and optional backtest report.")
    parser.add_argument("--wallet-limit", type=int, default=None)
    parser.add_argument("--leaderboard-limit", type=int, default=20)
    parser.add_argument("--as-of", default=None, help="ISO datetime used as scoring cutoff.")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--high-confidence-only", action="store_true")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--strategy-size", type=int, default=10)
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    engine = make_engine(args.database_url)
    result = run_smart_score(
        engine,
        wallet_limit=args.wallet_limit,
        leaderboard_limit=args.leaderboard_limit,
        as_of=_parse_datetime(args.as_of),
        lookback_days=args.lookback_days,
        high_confidence_only=args.high_confidence_only,
        run_backtest=args.backtest,
        validation_days=args.validation_days,
        strategy_size=args.strategy_size,
    )
    print(json.dumps(result.__dict__, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
