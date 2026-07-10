from __future__ import annotations

import argparse
import json
import time
from typing import Any

from backend.app.analytics.continuous_sampling import run_continuous_sampling_cycle
from backend.app.core.config import get_settings
from backend.app.db.database import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuously poll paper wallets, archive their books, and simulate orders."
    )
    parser.add_argument("--repeat-seconds", type=int, default=60)
    parser.add_argument("--max-cycles", type=int, default=1, help="0 repeats until interrupted.")
    parser.add_argument("--wallet-limit", type=int, default=50)
    parser.add_argument("--trade-page-limit", type=int, default=100)
    parser.add_argument("--trade-max-pages", type=int, default=2)
    parser.add_argument("--token-limit", type=int, default=30)
    parser.add_argument("--token-recent-hours", type=int, default=168)
    parser.add_argument("--paper-lookback-minutes", type=int, default=120)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    engine = make_engine(args.database_url)
    settings = get_settings()
    cycle = 0
    try:
        while True:
            cycle += 1
            try:
                result = run_continuous_sampling_cycle(
                    settings,
                    engine,
                    wallet_limit=args.wallet_limit,
                    trade_page_limit=args.trade_page_limit,
                    trade_max_pages=args.trade_max_pages,
                    token_limit=args.token_limit,
                    token_recent_hours=args.token_recent_hours,
                    paper_lookback_minutes=args.paper_lookback_minutes,
                )
                payload: dict[str, Any] = {**result.__dict__, "cycle": cycle}
            except Exception as exc:  # noqa: BLE001 - survive transient stage failures.
                payload = {
                    "cycle": cycle,
                    "status": "failed",
                    "errors": {"cycle": f"{type(exc).__name__}: {exc}"},
                }
            print(json.dumps(payload, sort_keys=True, default=str), flush=True)
            if args.repeat_seconds <= 0 or (
                args.max_cycles > 0 and cycle >= args.max_cycles
            ):
                break
            time.sleep(args.repeat_seconds)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped", "cycle": cycle}), flush=True)


if __name__ == "__main__":
    main()
