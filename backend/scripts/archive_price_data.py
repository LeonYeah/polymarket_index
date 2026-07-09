from __future__ import annotations

import argparse
import json
from typing import Any

from backend.app.collectors.price_data import run_price_archive_sync
from backend.app.core.config import get_settings
from backend.app.db.database import make_engine


def _json_default(value: Any) -> str:
    return str(value)


def _parse_tokens(value: str | None) -> list[str] | None:
    if value is None:
        return None
    tokens = [item.strip() for item in value.split(",") if item.strip()]
    return tokens or None


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive read-only Polymarket prices and order books.")
    parser.add_argument("--tokens", default=None, help="Comma-separated CLOB token IDs. Defaults to active DB tokens.")
    parser.add_argument("--token-limit", type=int, default=None)
    parser.add_argument("--interval", default=None)
    parser.add_argument("--fidelity", type=int, default=None)
    parser.add_argument("--start-ts", type=int, default=None)
    parser.add_argument("--end-ts", type=int, default=None)
    parser.add_argument("--depth-limit", type=int, default=None)
    parser.add_argument("--websocket-seconds", type=float, default=None)
    parser.add_argument("--websocket-event-limit", type=int, default=None)
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--skip-orderbook", action="store_true")
    parser.add_argument("--websocket", action="store_true")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    settings = get_settings()
    engine = make_engine(args.database_url)
    result = run_price_archive_sync(
        settings,
        engine,
        token_ids=_parse_tokens(args.tokens),
        token_limit=args.token_limit,
        include_price_history=not args.skip_history,
        include_orderbook=not args.skip_orderbook,
        include_websocket=args.websocket,
        interval=args.interval,
        fidelity=args.fidelity,
        start_ts=args.start_ts,
        end_ts=args.end_ts,
        depth_limit=args.depth_limit,
        websocket_seconds=args.websocket_seconds,
        websocket_event_limit=args.websocket_event_limit,
    )
    print(json.dumps(result.__dict__, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
