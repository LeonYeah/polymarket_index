from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.collectors.market_data import (
    market_matches_categories,
    normalize_holders,
    normalize_live_volume_snapshots,
    normalize_market_bundle,
    parse_datetime,
    parse_categories,
    parse_decimal,
    parse_json_array,
)


def test_parse_json_array_accepts_gamma_string_fields() -> None:
    assert parse_json_array('["Yes", "No"]') == ["Yes", "No"]
    assert parse_json_array("a,b") == ["a", "b"]
    assert parse_json_array(None) == []


def test_parse_categories_normalizes_csv_values() -> None:
    assert parse_categories("Politics, Finance,Tech") == {"politics", "finance", "tech"}
    assert parse_categories("") == set()


def test_parse_datetime_normalizes_milliseconds_to_utc() -> None:
    parsed = parse_datetime("1710000000000")
    assert parsed == datetime.fromtimestamp(1710000000, UTC)


def test_parse_decimal_keeps_exact_string_value() -> None:
    assert parse_decimal("853067.0079670154") == Decimal("853067.0079670154")


def test_normalize_market_bundle_maps_tokens_by_outcome_order() -> None:
    raw = {
        "id": "540817",
        "conditionId": "0xabc",
        "question": "Example?",
        "slug": "example",
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "orderMinSize": 5,
        "orderPriceMinTickSize": "0.01",
        "volume": "100.25",
        "liquidity": "20.5",
        "clobTokenIds": '["111", "222"]',
        "outcomes": '["Yes", "No"]',
        "events": [
            {
                "id": "event-1",
                "ticker": "event",
                "slug": "event",
                "title": "Event",
                "category": "Politics",
                "active": True,
                "closed": False,
            }
        ],
    }

    market, events, tokens = normalize_market_bundle(raw, "run-1")

    assert market is not None
    assert market["condition_id"] == "0xabc"
    assert market["gamma_event_id"] == "event-1"
    assert market["order_price_min_tick_size"] == Decimal("0.01")
    assert events[0]["gamma_event_id"] == "event-1"
    assert [(token["token_id"], token["outcome"], token["mapping_status"]) for token in tokens] == [
        ("111", "Yes", "mapped"),
        ("222", "No", "mapped"),
    ]


def test_market_matches_embedded_event_category() -> None:
    raw = {"events": [{"category": "Finance"}]}
    assert market_matches_categories(raw, {"finance"})
    assert not market_matches_categories(raw, {"sports"})
    assert market_matches_categories(raw, set())


def test_market_matches_categories_keeps_uncategorized_markets() -> None:
    assert market_matches_categories({"events": [{}]}, {"politics", "finance", "tech"})


def test_normalize_market_bundle_marks_mismatched_mapping_failed() -> None:
    market, _, tokens = normalize_market_bundle(
        {
            "id": "1",
            "conditionId": "0xabc",
            "clobTokenIds": '["111", "222"]',
            "outcomes": '["Yes"]',
        },
        "run-1",
    )

    assert market is not None
    assert {token["mapping_status"] for token in tokens} == {"failed"}
    assert {token["mapping_error"] for token in tokens} == {"token_outcome_length_mismatch"}


def test_normalize_live_volume_snapshots_extracts_condition_volume() -> None:
    rows = normalize_live_volume_snapshots(
        [{"total": 10, "markets": [{"market": "0xabc", "value": 7.5}]}],
        "run-1",
        datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert rows[0]["condition_id"] == "0xabc"
    assert rows[0]["live_volume"] == Decimal("7.5")


def test_normalize_holders_lowercases_wallets_and_preserves_token() -> None:
    rows = normalize_holders(
        [
            {
                "token": "111",
                "holders": [
                    {
                        "proxyWallet": "0xABC",
                        "amount": 12.34,
                        "outcomeIndex": 0,
                        "name": "alice",
                        "verified": True,
                    }
                ],
            }
        ],
        condition_id="0xmarket",
        run_id="run-1",
        snapshot_at=datetime(2026, 7, 9, tzinfo=UTC),
    )

    assert rows[0]["token_id"] == "111"
    assert rows[0]["wallet_address"] == "0xabc"
    assert rows[0]["amount"] == Decimal("12.34")
