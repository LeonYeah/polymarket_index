from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import Engine

from backend.app.core.config import Settings
from backend.app.core.run_context import new_run_id
from backend.app.db.repository import MarketDataRepository


@dataclass(frozen=True)
class IngestionResult:
    run_id: str
    status: str
    counters: dict[str, int]
    started_at: datetime
    finished_at: datetime
    warnings: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, UTC)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.isdigit():
            return parse_datetime(int(candidate))
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def parse_json_array(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return []
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return [item.strip() for item in candidate.split(",") if item.strip()]
        return parsed if isinstance(parsed, list) else []
    return []


def first_list(payload: Any, key: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    return []


def row_count(payload: Any, key: str) -> int:
    return len(first_list(payload, key))


def normalize_event(raw: Mapping[str, Any], run_id: str) -> dict[str, Any] | None:
    gamma_event_id = raw.get("id")
    if gamma_event_id is None:
        return None
    return {
        "gamma_event_id": str(gamma_event_id),
        "ticker": raw.get("ticker"),
        "slug": raw.get("slug"),
        "title": raw.get("title"),
        "description": raw.get("description"),
        "category": raw.get("category"),
        "active": raw.get("active"),
        "closed": raw.get("closed"),
        "archived": raw.get("archived"),
        "start_date": parse_datetime(raw.get("startDate")),
        "end_date": parse_datetime(raw.get("endDate")),
        "raw": dict(raw),
        "source": "gamma",
        "ingestion_run_id": run_id,
    }


def normalize_market_bundle(
    raw: Mapping[str, Any], run_id: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    condition_id = raw.get("conditionId") or raw.get("condition_id")
    if not condition_id:
        return None, [], []

    embedded_events = [event for event in raw.get("events", []) if isinstance(event, Mapping)]
    normalized_events = [
        event for event in (normalize_event(event, run_id) for event in embedded_events) if event
    ]
    first_event = normalized_events[0] if normalized_events else None
    outcomes = [str(item) for item in parse_json_array(raw.get("outcomes"))]
    token_ids = [str(item) for item in parse_json_array(raw.get("clobTokenIds"))]
    mapping_status = "mapped" if token_ids and len(token_ids) == len(outcomes) else "failed"
    mapping_error = None if mapping_status == "mapped" else "token_outcome_length_mismatch"

    market = {
        "condition_id": str(condition_id),
        "gamma_market_id": str(raw["id"]) if raw.get("id") is not None else None,
        "gamma_event_id": first_event["gamma_event_id"] if first_event else None,
        "slug": raw.get("slug"),
        "question": raw.get("question"),
        "category": first_event.get("category") if first_event else raw.get("category"),
        "active": raw.get("active"),
        "closed": raw.get("closed"),
        "archived": raw.get("archived"),
        "accepting_orders": raw.get("acceptingOrders"),
        "end_date": parse_datetime(raw.get("endDate")),
        "order_min_size": parse_decimal(raw.get("orderMinSize")),
        "order_price_min_tick_size": parse_decimal(raw.get("orderPriceMinTickSize")),
        "volume": parse_decimal(raw.get("volume")),
        "liquidity": parse_decimal(raw.get("liquidity")),
        "raw": dict(raw),
        "source": "gamma",
        "ingestion_run_id": run_id,
    }

    tokens = []
    for index, token_id in enumerate(token_ids):
        tokens.append(
            {
                "token_id": token_id,
                "condition_id": str(condition_id),
                "gamma_market_id": market["gamma_market_id"],
                "outcome_index": index,
                "outcome": outcomes[index] if index < len(outcomes) else None,
                "mapping_status": mapping_status,
                "mapping_error": mapping_error,
                "verified_at": None,
                "raw": {
                    "clobTokenIds": raw.get("clobTokenIds"),
                    "outcomes": raw.get("outcomes"),
                },
                "source": "gamma",
                "ingestion_run_id": run_id,
            }
        )
    return market, normalized_events, tokens


def market_category(raw: Mapping[str, Any]) -> str | None:
    if raw.get("category"):
        return str(raw["category"])
    embedded_events = [event for event in raw.get("events", []) if isinstance(event, Mapping)]
    for event in embedded_events:
        if event.get("category"):
            return str(event["category"])
    return None


def parse_categories(value: str | None) -> set[str]:
    if value is None:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def market_matches_categories(raw: Mapping[str, Any], categories: set[str]) -> bool:
    if not categories:
        return True
    category = market_category(raw)
    if category is None:
        return True
    return category.lower() in categories


def normalize_market_snapshot(
    raw: Mapping[str, Any], run_id: str, snapshot_at: datetime
) -> dict[str, Any] | None:
    condition_id = raw.get("conditionId") or raw.get("condition_id")
    if not condition_id:
        return None
    return {
        "snapshot_at": snapshot_at,
        "condition_id": str(condition_id),
        "gamma_market_id": str(raw["id"]) if raw.get("id") is not None else None,
        "source_endpoint": "gamma.markets.keyset",
        "open_interest": parse_decimal(raw.get("openInterest")),
        "live_volume": None,
        "liquidity": parse_decimal(raw.get("liquidity")),
        "volume": parse_decimal(raw.get("volume")),
        "raw": dict(raw),
        "source": "gamma",
        "ingestion_run_id": run_id,
    }


def normalize_oi_snapshot(
    raw: Mapping[str, Any], run_id: str, snapshot_at: datetime
) -> dict[str, Any] | None:
    market = raw.get("market")
    if not market:
        return None
    market_id = str(market)
    return {
        "snapshot_at": snapshot_at,
        "condition_id": market_id if market_id.startswith("0x") else None,
        "gamma_market_id": None if market_id.startswith("0x") else market_id,
        "source_endpoint": "data.oi",
        "open_interest": parse_decimal(raw.get("value")),
        "live_volume": None,
        "liquidity": None,
        "volume": None,
        "raw": dict(raw),
        "source": "data",
        "ingestion_run_id": run_id,
    }


def normalize_live_volume_snapshots(
    payload: Any, run_id: str, snapshot_at: datetime
) -> list[dict[str, Any]]:
    snapshots = []
    groups = payload if isinstance(payload, list) else []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        for item in group.get("markets", []):
            if not isinstance(item, Mapping):
                continue
            condition_id = item.get("market")
            if not condition_id:
                continue
            snapshots.append(
                {
                    "snapshot_at": snapshot_at,
                    "condition_id": str(condition_id),
                    "gamma_market_id": None,
                    "source_endpoint": "data.live-volume",
                    "open_interest": None,
                    "live_volume": parse_decimal(item.get("value")),
                    "liquidity": None,
                    "volume": None,
                    "raw": dict(item),
                    "source": "data",
                    "ingestion_run_id": run_id,
                }
            )
    return snapshots


def normalize_holders(
    payload: Any,
    *,
    condition_id: str,
    run_id: str,
    snapshot_at: datetime,
) -> list[dict[str, Any]]:
    rows = []
    token_groups = payload if isinstance(payload, list) else []
    for group in token_groups:
        if not isinstance(group, Mapping):
            continue
        token_id = str(group.get("token") or "")
        if not token_id:
            continue
        holders = group.get("holders", [])
        if not isinstance(holders, list):
            continue
        for rank, holder in enumerate(holders, start=1):
            if not isinstance(holder, Mapping):
                continue
            wallet = holder.get("proxyWallet") or holder.get("wallet")
            if not wallet:
                continue
            rows.append(
                {
                    "snapshot_at": snapshot_at,
                    "condition_id": condition_id,
                    "token_id": token_id,
                    "wallet_address": str(wallet).lower(),
                    "holder_rank": rank,
                    "amount": parse_decimal(holder.get("amount")),
                    "outcome_index": holder.get("outcomeIndex"),
                    "pseudonym": holder.get("pseudonym"),
                    "display_name": holder.get("name"),
                    "verified": holder.get("verified"),
                    "raw": dict(holder),
                    "source": "data",
                    "ingestion_run_id": run_id,
                }
            )
    return rows


class MarketDataIngestion:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self.settings = settings
        self.engine = engine

    async def run(
        self,
        *,
        max_markets: int | None = None,
        page_limit: int | None = None,
        holders_market_limit: int | None = None,
        holders_limit: int | None = None,
        categories: str | None = None,
        token_verification_limit: int | None = None,
    ) -> IngestionResult:
        run_id = new_run_id("market_data")
        started_at = utc_now()
        max_markets = (
            self.settings.market_ingestion_max_markets if max_markets is None else max_markets
        )
        page_limit = self.settings.market_ingestion_page_limit if page_limit is None else page_limit
        holders_market_limit = (
            self.settings.market_ingestion_holders_market_limit
            if holders_market_limit is None
            else holders_market_limit
        )
        holders_limit = (
            self.settings.market_ingestion_holders_limit if holders_limit is None else holders_limit
        )
        category_filter = parse_categories(
            self.settings.market_ingestion_target_categories if categories is None else categories
        )
        token_verification_limit = (
            self.settings.market_ingestion_token_verification_limit
            if token_verification_limit is None
            else token_verification_limit
        )
        counters: dict[str, int] = {
            "events": 0,
            "markets": 0,
            "tokens": 0,
            "token_verifications": 0,
            "token_mapping_failures": 0,
            "liquidity_snapshots": 0,
            "holders": 0,
            "raw_responses": 0,
            "market_pages": 0,
            "uncategorized_markets": 0,
            "priority_markets_requested": 0,
            "priority_markets_refreshed": 0,
            "priority_market_failures": 0,
        }
        warnings: list[str] = []
        params = {
            "max_markets": max_markets,
            "page_limit": page_limit,
            "holders_market_limit": holders_market_limit,
            "holders_limit": holders_limit,
            "categories": sorted(category_filter),
            "token_verification_limit": token_verification_limit,
        }

        with self.engine.begin() as connection:
            repository = MarketDataRepository(connection)
            repository.start_run(run_id, "market_data_ingestion", "polymarket", started_at, params)
            priority_targets = repository.fetch_open_paper_market_targets()
            counters["priority_markets_requested"] = len(priority_targets)
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.api_probe_timeout_seconds
                ) as client:
                    priority_markets, priority_failures = await self._fetch_priority_markets(
                        client, run_id, repository, priority_targets, warnings
                    )
                    counters["priority_markets_refreshed"] = len(priority_markets)
                    counters["priority_market_failures"] = priority_failures
                    counters["raw_responses"] += len(priority_markets)
                    markets_payloads = await self._fetch_market_pages(
                        client,
                        run_id,
                        repository,
                        max_markets,
                        page_limit,
                        category_filter,
                        warnings,
                    )
                    page_markets = [
                        market
                        for payload in markets_payloads
                        for market in first_list(payload, "markets")
                        if isinstance(market, Mapping)
                        and market_matches_categories(market, category_filter)
                    ][:max_markets]
                    markets_by_condition = {
                        str(market.get("conditionId") or market.get("condition_id")): market
                        for market in [*page_markets, *priority_markets]
                        if market.get("conditionId") or market.get("condition_id")
                    }
                    markets_raw = list(markets_by_condition.values())
                    uncategorized_count = sum(
                        1 for market in markets_raw if market_category(market) is None
                    )
                    counters["uncategorized_markets"] += uncategorized_count
                    if uncategorized_count and category_filter:
                        warnings.append("gamma_market_category_missing_retained_for_ingestion")
                    events_raw = await self._fetch_events_page(
                        client, run_id, repository, page_limit
                    )
                    counters["raw_responses"] += len(markets_payloads) + 1
                    counters["market_pages"] += len(markets_payloads)

                    normalized_events = [
                        event
                        for event in (normalize_event(event, run_id) for event in events_raw)
                        if event
                    ]
                    normalized_markets = []
                    normalized_tokens = []
                    market_snapshots = []
                    snapshot_at = utc_now()
                    for raw_market in markets_raw:
                        market, embedded_events, tokens = normalize_market_bundle(
                            raw_market, run_id
                        )
                        if market:
                            normalized_markets.append(market)
                            normalized_events.extend(embedded_events)
                            normalized_tokens.extend(tokens)
                        snapshot = normalize_market_snapshot(raw_market, run_id, snapshot_at)
                        if snapshot:
                            market_snapshots.append(snapshot)

                    counters["events"] += repository.upsert_events(
                        _dedupe_by(normalized_events, "gamma_event_id"), run_id
                    )
                    counters["markets"] += repository.upsert_markets(normalized_markets, run_id)
                    counters["tokens"] += repository.upsert_tokens(normalized_tokens, run_id)
                    token_verification_counters = await self._verify_tokens(
                        client,
                        repository,
                        run_id,
                        normalized_tokens[:token_verification_limit],
                    )
                    counters["token_verifications"] += token_verification_counters["verified"]
                    counters["token_mapping_failures"] += token_verification_counters["failed"]
                    counters["raw_responses"] += token_verification_counters["raw_responses"]
                    counters["liquidity_snapshots"] += repository.insert_liquidity_snapshots(
                        market_snapshots, run_id
                    )

                    oi_payload = await self._fetch_json(
                        client, repository, run_id, "data", "/oi", {"limit": page_limit}, "value"
                    )
                    counters["raw_responses"] += 1
                    oi_snapshots = [
                        snapshot
                        for snapshot in (
                            normalize_oi_snapshot(item, run_id, utc_now())
                            for item in (oi_payload if isinstance(oi_payload, list) else [])
                            if isinstance(item, Mapping)
                        )
                        if snapshot
                    ]
                    counters["liquidity_snapshots"] += repository.insert_liquidity_snapshots(
                        oi_snapshots, run_id
                    )

                    holder_targets = sorted(
                        normalized_markets,
                        key=lambda item: item.get("volume") or 0,
                        reverse=True,
                    )[:holders_market_limit]
                    for market in holder_targets:
                        if not market.get("gamma_market_id"):
                            continue
                        live_payload = await self._fetch_json(
                            client,
                            repository,
                            run_id,
                            "data",
                            "/live-volume",
                            {"id": market["gamma_market_id"]},
                            "markets",
                        )
                        counters["raw_responses"] += 1
                        counters["liquidity_snapshots"] += repository.insert_liquidity_snapshots(
                            normalize_live_volume_snapshots(live_payload, run_id, utc_now()), run_id
                        )

                        holders_payload = await self._fetch_json(
                            client,
                            repository,
                            run_id,
                            "data",
                            "/holders",
                            {"market": market["condition_id"], "limit": holders_limit},
                            "holders",
                        )
                        counters["raw_responses"] += 1
                        counters["holders"] += repository.insert_holders(
                            normalize_holders(
                                holders_payload,
                                condition_id=market["condition_id"],
                                run_id=run_id,
                                snapshot_at=utc_now(),
                            ),
                            run_id,
                        )

                finished_at = utc_now()
                repository.finish_run(run_id, "succeeded", finished_at, counters)
                return IngestionResult(
                    run_id, "succeeded", counters, started_at, finished_at, warnings
                )
            except Exception as exc:
                finished_at = utc_now()
                repository.finish_run(run_id, "failed", finished_at, counters, str(exc))
                raise

    async def _fetch_priority_markets(
        self,
        client: httpx.AsyncClient,
        run_id: str,
        repository: MarketDataRepository,
        targets: list[dict[str, str]],
        warnings: list[str],
    ) -> tuple[list[Mapping[str, Any]], int]:
        gamma_base = str(self.settings.polymarket_gamma_base_url).rstrip("/")
        markets: list[Mapping[str, Any]] = []
        failures = 0
        for target in targets:
            condition_id = target["condition_id"]
            gamma_market_id = target["gamma_market_id"]
            if not gamma_market_id:
                failures += 1
                warnings.append(f"priority_market_missing_gamma_id:{condition_id}")
                continue
            try:
                payload = await self._fetch_json(
                    client,
                    repository,
                    run_id,
                    "gamma",
                    f"{gamma_base}/markets/{gamma_market_id}",
                    {},
                    "market",
                    absolute_url=True,
                )
            except (httpx.HTTPError, ValueError) as exc:
                failures += 1
                warnings.append(
                    f"priority_market_refresh_failed:{condition_id}:{type(exc).__name__}"
                )
                continue
            if not isinstance(payload, Mapping):
                failures += 1
                warnings.append(f"priority_market_invalid_payload:{condition_id}")
                continue
            actual_condition_id = payload.get("conditionId") or payload.get("condition_id")
            if str(actual_condition_id) != condition_id:
                failures += 1
                warnings.append(f"priority_market_condition_mismatch:{condition_id}")
                continue
            markets.append(payload)
        return markets, failures

    async def _fetch_market_pages(
        self,
        client: httpx.AsyncClient,
        run_id: str,
        repository: MarketDataRepository,
        max_markets: int,
        page_limit: int,
        category_filter: set[str],
        warnings: list[str],
    ) -> list[Any]:
        gamma_base = str(self.settings.polymarket_gamma_base_url).rstrip("/")
        payloads: list[Any] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        seen_first_ids: set[str] = set()
        matched_count = 0
        max_pages = 200
        while matched_count < max_markets:
            params: dict[str, Any] = {"limit": page_limit, "active": "true"}
            if cursor:
                params["after_cursor"] = cursor
            payload = await self._fetch_json(
                client,
                repository,
                run_id,
                "gamma",
                f"{gamma_base}/markets/keyset",
                params,
                "markets",
                absolute_url=True,
            )
            markets = first_list(payload, "markets")
            if not markets:
                break
            first_id = str(markets[0].get("id")) if isinstance(markets[0], Mapping) else ""
            next_cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
            if first_id in seen_first_ids:
                warnings.append("gamma_markets_keyset_repeated_first_id")
                break
            seen_first_ids.add(first_id)
            payloads.append(payload)
            matched_count += sum(
                1
                for market in markets
                if isinstance(market, Mapping)
                and market_matches_categories(market, category_filter)
            )
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(str(next_cursor))
            cursor = str(next_cursor)
            if len(payloads) >= max_pages:
                warnings.append("gamma_markets_keyset_max_pages_reached")
                break
        return payloads

    async def _fetch_events_page(
        self,
        client: httpx.AsyncClient,
        run_id: str,
        repository: MarketDataRepository,
        page_limit: int,
    ) -> list[Any]:
        gamma_base = str(self.settings.polymarket_gamma_base_url).rstrip("/")
        payload = await self._fetch_json(
            client,
            repository,
            run_id,
            "gamma",
            f"{gamma_base}/events/keyset",
            {"limit": page_limit},
            "events",
            absolute_url=True,
        )
        return [event for event in first_list(payload, "events") if isinstance(event, Mapping)]

    async def _fetch_json(
        self,
        client: httpx.AsyncClient,
        repository: MarketDataRepository,
        run_id: str,
        source: str,
        endpoint: str,
        params: Mapping[str, Any],
        count_key: str,
        *,
        absolute_url: bool = False,
    ) -> Any:
        started = time.perf_counter()
        if absolute_url:
            url = endpoint
        elif source == "data":
            url = f"{str(self.settings.polymarket_data_base_url).rstrip('/')}{endpoint}"
        else:
            url = endpoint
        response = await client.get(url, params=params)
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        payload = response.json()
        repository.record_raw_response(
            run_id=run_id,
            source=source,
            endpoint=endpoint,
            request_params=params,
            status_code=response.status_code,
            duration_ms=duration_ms,
            row_count=row_count(payload, count_key),
            captured_at=utc_now(),
            body=payload,
        )
        return payload

    async def _verify_tokens(
        self,
        client: httpx.AsyncClient,
        repository: MarketDataRepository,
        run_id: str,
        tokens: list[dict[str, Any]],
    ) -> dict[str, int]:
        counters = {"verified": 0, "failed": 0, "raw_responses": 0}
        clob_base = str(self.settings.polymarket_clob_base_url).rstrip("/")
        for token in tokens:
            token_id = token["token_id"]
            started = time.perf_counter()
            response = await client.get(f"{clob_base}/markets-by-token/{token_id}")
            duration_ms = int((time.perf_counter() - started) * 1000)
            try:
                payload = response.json()
            except ValueError:
                payload = {"body": response.text[:1000]}
            repository.record_raw_response(
                run_id=run_id,
                source="clob",
                endpoint=f"{clob_base}/markets-by-token/{{token_id}}",
                request_params={"token_id": token_id},
                status_code=response.status_code,
                duration_ms=duration_ms,
                row_count=1 if response.is_success else 0,
                captured_at=utc_now(),
                body=payload,
            )
            counters["raw_responses"] += 1
            expected_condition_id = token["condition_id"]
            verified_token_ids = {
                str(payload.get("primary_token_id")),
                str(payload.get("secondary_token_id")),
            }
            actual_condition_id = payload.get("condition_id")
            if (
                response.is_success
                and str(actual_condition_id) == expected_condition_id
                and token_id in verified_token_ids
            ):
                repository.update_token_mapping(
                    token_id=token_id,
                    run_id=run_id,
                    mapping_status="verified",
                    mapping_error=None,
                    verified_at=utc_now(),
                    raw={"clob_markets_by_token": payload},
                )
                counters["verified"] += 1
            else:
                repository.update_token_mapping(
                    token_id=token_id,
                    run_id=run_id,
                    mapping_status="failed",
                    mapping_error="clob_markets_by_token_mismatch",
                    verified_at=utc_now() if response.is_success else None,
                    raw={"clob_markets_by_token": payload},
                )
                counters["failed"] += 1
        return counters


def _dedupe_by(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    deduped: dict[Any, dict[str, Any]] = {}
    for row in rows:
        deduped[row[key]] = row
    return list(deduped.values())


async def run_market_ingestion(
    settings: Settings, engine: Engine, **kwargs: Any
) -> IngestionResult:
    ingestion = MarketDataIngestion(settings, engine)
    return await ingestion.run(**kwargs)


def run_market_ingestion_sync(settings: Settings, engine: Engine, **kwargs: Any) -> IngestionResult:
    return asyncio.run(run_market_ingestion(settings, engine, **kwargs))
