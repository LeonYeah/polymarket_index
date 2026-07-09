from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from backend.app.core.config import get_settings
from backend.app.core.run_context import new_run_id


@dataclass(frozen=True)
class ProbeCase:
    source: str
    name: str
    method: str
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    expected: str = "normal"


def _json_default(value: Any) -> str:
    return str(value)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        redacted_keys = {"api_key", "apikey", "authorization", "cookie", "signature", "private_key"}
        return {
            key: "***REDACTED***" if key.lower() in redacted_keys else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:50]]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n")


def _first_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "markets", "events", "items", "results"):
            item = payload.get(key)
            if isinstance(item, list):
                return item
    return []


def _market_fields(market: dict[str, Any]) -> tuple[str | None, list[str]]:
    condition_id = market.get("conditionId") or market.get("condition_id")
    token_ids = market.get("clobTokenIds") or market.get("clob_token_ids") or []
    if isinstance(token_ids, str):
        try:
            parsed = json.loads(token_ids)
            token_ids = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            token_ids = [item.strip() for item in token_ids.split(",") if item.strip()]
    return condition_id, [str(token_id) for token_id in token_ids]


async def _get(client: httpx.AsyncClient, case: ProbeCase) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = await client.request(case.method, case.url, params=case.params)
        duration_ms = int((time.perf_counter() - started) * 1000)
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            body: Any = response.json()
        else:
            body = response.text[:4000]
        return {
            "case": case.__dict__,
            "ok": 200 <= response.status_code < 400,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "headers": {
                "content-type": content_type,
                "retry-after": response.headers.get("retry-after"),
                "x-ratelimit-limit": response.headers.get("x-ratelimit-limit"),
                "x-ratelimit-remaining": response.headers.get("x-ratelimit-remaining"),
            },
            "body": _sanitize(body),
        }
    except Exception as exc:  # noqa: BLE001 - probe must record failures instead of hiding them.
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "case": case.__dict__,
            "ok": False,
            "status_code": None,
            "duration_ms": duration_ms,
            "error": type(exc).__name__,
            "message": str(exc),
        }


async def _discover(gamma_base: str, data_base: str, timeout: float) -> dict[str, Any]:
    discovered: dict[str, Any] = {"condition_id": None, "token_id": None, "gamma_market_id": None, "wallet": None}
    async with httpx.AsyncClient(timeout=timeout) as client:
        market_case = ProbeCase(
            "gamma",
            "markets_keyset_discovery",
            "GET",
            f"{gamma_base}/markets/keyset",
            {"limit": 5, "active": "true", "closed": "false"},
        )
        market_result = await _get(client, market_case)
        for market in _first_list(market_result.get("body")):
            if not isinstance(market, dict):
                continue
            condition_id, token_ids = _market_fields(market)
            if condition_id and token_ids:
                discovered["condition_id"] = condition_id
                discovered["token_id"] = token_ids[0]
                discovered["gamma_market_id"] = market.get("id")
                break

        trades_case = ProbeCase(
            "data",
            "trades_discovery",
            "GET",
            f"{data_base}/trades",
            {"limit": 10, "takerOnly": "false"},
        )
        trades_result = await _get(client, trades_case)
        for trade in _first_list(trades_result.get("body")):
            if not isinstance(trade, dict):
                continue
            wallet = trade.get("proxyWallet") or trade.get("maker") or trade.get("wallet")
            if wallet:
                discovered["wallet"] = wallet
                break
    return discovered


async def _probe_websocket(ws_base: str, token_id: str | None, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    if not token_id:
        return {"ok": False, "error": "missing_token_id", "duration_ms": 0}
    try:
        import websockets

        url = f"{ws_base.rstrip('/')}/market"
        async with websockets.connect(url, open_timeout=timeout, close_timeout=2) as websocket:
            await websocket.send(json.dumps({"assets_ids": [token_id], "type": "market"}))
            message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            return {
                "ok": True,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "message": _sanitize(json.loads(message) if message.startswith(("{", "[")) else message),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "error": type(exc).__name__,
            "message": str(exc),
        }


def _build_cases(settings: Any, discovered: dict[str, Any]) -> list[ProbeCase]:
    gamma = str(settings.polymarket_gamma_base_url).rstrip("/")
    data = str(settings.polymarket_data_base_url).rstrip("/")
    clob = str(settings.polymarket_clob_base_url).rstrip("/")
    token_id = discovered.get("token_id") or "invalid-token-id"
    condition_id = discovered.get("condition_id") or "invalid-condition-id"
    wallet = discovered.get("wallet") or "0x0000000000000000000000000000000000000000"
    gamma_market_id = discovered.get("gamma_market_id") or condition_id

    return [
        ProbeCase("gamma", "markets_keyset_normal", "GET", f"{gamma}/markets/keyset", {"limit": 5}),
        ProbeCase("gamma", "events_keyset_normal", "GET", f"{gamma}/events/keyset", {"limit": 5}),
        ProbeCase("gamma", "markets_keyset_empty", "GET", f"{gamma}/markets/keyset", {"limit": 1, "slug": "__no_such_market__"}),
        ProbeCase("gamma", "markets_keyset_invalid", "GET", f"{gamma}/markets/keyset", {"limit": "not-int"}, "invalid"),
        ProbeCase("data", "leaderboard_normal", "GET", f"{data}/v1/leaderboard", {"limit": 10}),
        ProbeCase("data", "holders_normal", "GET", f"{data}/holders", {"market": condition_id, "limit": 10}),
        ProbeCase("data", "positions_normal", "GET", f"{data}/positions", {"user": wallet, "limit": 10}),
        ProbeCase("data", "closed_positions_normal", "GET", f"{data}/closed-positions", {"user": wallet, "limit": 10}),
        ProbeCase("data", "trades_taker_only_true", "GET", f"{data}/trades", {"limit": 20, "takerOnly": "true"}),
        ProbeCase("data", "trades_taker_only_false", "GET", f"{data}/trades", {"limit": 20, "takerOnly": "false"}),
        ProbeCase("data", "oi_normal", "GET", f"{data}/oi", {"limit": 10}),
        ProbeCase("data", "live_volume_normal", "GET", f"{data}/live-volume", {"id": gamma_market_id}),
        ProbeCase("data", "trades_empty", "GET", f"{data}/trades", {"user": "0x0000000000000000000000000000000000000000", "limit": 10}),
        ProbeCase("data", "positions_invalid", "GET", f"{data}/positions", {"user": "not-a-wallet"}, "invalid"),
        ProbeCase("clob", "book_normal", "GET", f"{clob}/book", {"token_id": token_id}),
        ProbeCase("clob", "prices_history_normal", "GET", f"{clob}/prices-history", {"market": token_id, "interval": "1d"}),
        ProbeCase("clob", "market_by_condition", "GET", f"{clob}/markets/{condition_id}"),
        ProbeCase("clob", "book_invalid", "GET", f"{clob}/book", {"token_id": "invalid-token-id"}, "invalid"),
    ]


async def run_probe(output_dir: Path) -> dict[str, Any]:
    settings = get_settings()
    run_id = new_run_id("api_probe")
    timeout = settings.api_probe_timeout_seconds
    output_dir.mkdir(parents=True, exist_ok=True)

    discovered = await _discover(
        str(settings.polymarket_gamma_base_url).rstrip("/"),
        str(settings.polymarket_data_base_url).rstrip("/"),
        timeout,
    )

    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for case in _build_cases(settings, discovered):
            result = await _get(client, case)
            sample_name = f"{run_id}_{case.source}_{case.name}.json"
            sample_path = output_dir / sample_name
            _write_json(sample_path, result)
            result["sample_path"] = str(sample_path)
            results.append(result)

    ws_result = await _probe_websocket(
        str(settings.polymarket_ws_base_url).rstrip("/"),
        discovered.get("token_id"),
        timeout,
    )
    ws_path = output_dir / f"{run_id}_websocket_market.json"
    _write_json(ws_path, ws_result)

    summary = {
        "run_id": run_id,
        "collected_at_utc": datetime.now(UTC).isoformat(),
        "discovered": discovered,
        "counts": {
            "total_http_cases": len(results),
            "ok_http_cases": sum(1 for result in results if result.get("ok")),
            "failed_http_cases": sum(1 for result in results if not result.get("ok")),
            "websocket_ok": bool(ws_result.get("ok")),
        },
        "results": [
            {
                "source": result["case"]["source"],
                "name": result["case"]["name"],
                "expected": result["case"]["expected"],
                "ok": result.get("ok"),
                "status_code": result.get("status_code"),
                "duration_ms": result.get("duration_ms"),
                "sample_path": result.get("sample_path"),
                "error": result.get("error"),
            }
            for result in results
        ],
        "websocket": {
            "ok": ws_result.get("ok"),
            "duration_ms": ws_result.get("duration_ms"),
            "sample_path": str(ws_path),
            "error": ws_result.get("error"),
        },
    }
    summary_path = output_dir / f"{run_id}_summary.json"
    _write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only Polymarket API probes.")
    parser.add_argument("--output-dir", default=None, help="Directory for sanitized JSON samples.")
    args = parser.parse_args()

    settings = get_settings()
    output_dir = Path(args.output_dir or settings.api_probe_output_dir)
    summary = asyncio.run(run_probe(output_dir))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

