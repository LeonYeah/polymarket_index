from __future__ import annotations

import argparse
import json
from typing import Any

from backend.app.analytics.pnl_runner import run_pnl_calculation
from backend.app.db.database import make_engine


def _json_default(value: Any) -> str:
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate wallet-market PnL and reconciliation checks.")
    parser.add_argument("--wallet-limit", type=int, default=None)
    parser.add_argument("--reconciliation-limit", type=int, default=30)
    parser.add_argument("--profile-limit", type=int, default=5)
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    engine = make_engine(args.database_url)
    result = run_pnl_calculation(
        engine,
        wallet_limit=args.wallet_limit,
        reconciliation_limit=args.reconciliation_limit,
        profile_limit=args.profile_limit,
    )
    print(json.dumps(result.__dict__, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
