from __future__ import annotations

import argparse
import json
import time
from typing import Any

from backend.app.analytics.paper_trading_runner import run_paper_trading
from backend.app.db.database import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Week08 paper copy-trading cycle.")
    parser.add_argument("--lookback-minutes", type=int, default=60)
    parser.add_argument("--signal-limit", type=int, default=500)
    parser.add_argument("--valuation-limit", type=int, default=1000)
    parser.add_argument("--order-type", choices=["FOK", "FAK", "GTC"], default="FAK")
    parser.add_argument(
        "--repeat-seconds",
        type=int,
        default=0,
        help="Repeat interval; 0 runs once. Use with a process supervisor for long sampling.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=1,
        help="Number of cycles; 0 repeats until interrupted when repeat-seconds is set.",
    )
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()
    engine = make_engine(args.database_url)
    cycle = 0
    while True:
        cycle += 1
        try:
            result = run_paper_trading(
                engine,
                lookback_minutes=args.lookback_minutes,
                signal_limit=args.signal_limit,
                valuation_limit=args.valuation_limit,
                order_type=args.order_type,
            )
            payload: dict[str, Any] = {**result.__dict__, "cycle": cycle}
        except Exception as exc:
            payload = {"cycle": cycle, "status": "failed", "error": str(exc)}
        print(json.dumps(payload, sort_keys=True, default=_json_default), flush=True)
        if args.repeat_seconds <= 0 or (args.max_cycles > 0 and cycle >= args.max_cycles):
            break
        time.sleep(args.repeat_seconds)


def _json_default(value: Any) -> str:
    return str(value)


if __name__ == "__main__":
    main()
