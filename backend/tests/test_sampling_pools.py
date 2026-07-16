from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.app.db.paper_trading_repository import PaperTradingRepository
from backend.app.db.price_repository import PriceArchiveRepository
from backend.app.db.wallet_repository import WalletDataRepository


class RecordingConnection:
    def __init__(self, results: list[list[Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = list(results or [])

    def execute(self, statement: object, params: dict[str, Any]) -> list[Any]:
        self.calls.append((str(statement), params))
        return self.results.pop(0) if self.results else []


def test_sampling_pool_ranks_25_candidates_without_relaxing_paper_pool() -> None:
    connection = RecordingConnection()
    repository = WalletDataRepository(connection)  # type: ignore[arg-type]

    assert repository.fetch_sampling_wallets(25) == []

    sql, params = connection.calls[0]
    assert params == {"research_limit": 25}
    assert "FROM wallet_candidates" in sql
    assert "ranked_research" in sql
    assert "paper_eligible" in sql
    assert "ls.score >= 60 AND ls.confidence >= 0.35" in sql
    assert "bool_or(research_sampled)" in sql
    assert "bool_or(paper_eligible)" in sql


def test_sampling_tokens_use_research_wallet_addresses() -> None:
    connection = RecordingConnection(
        results=[[SimpleNamespace(token_id="token-1"), SimpleNamespace(token_id="token-2")]]
    )
    repository = WalletDataRepository(connection)  # type: ignore[arg-type]
    repository.fetch_sampling_wallets = lambda _limit: [  # type: ignore[method-assign]
        {"wallet_address": "0xresearch"},
        {"wallet_address": "0xpaper"},
    ]

    tokens = repository.fetch_sampling_token_ids(
        limit=30,
        recent_hours=168,
        research_wallet_limit=25,
    )

    assert tokens == ["token-1", "token-2"]
    sql, params = connection.calls[0]
    assert "t.wallet_address = ANY(:wallet_addresses)" in sql
    assert params["wallet_addresses"] == ["0xresearch", "0xpaper"]
    assert params["limit"] == 30


def test_clv_selection_revisits_mature_incomplete_horizons() -> None:
    connection = RecordingConnection()
    repository = PriceArchiveRepository(connection)  # type: ignore[arg-type]

    assert repository.fetch_trades_for_clv(1000, ["0xresearch", "0xpaper"]) == []

    sql, params = connection.calls[0]
    assert params == {
        "limit": 1000,
        "restrict_wallets": True,
        "wallet_addresses": ["0xresearch", "0xpaper"],
    }
    assert "t.wallet_address = ANY(:wallet_addresses)" in sql
    assert "existing.trade_uid IS NULL" in sql
    assert "existing.clv_30s IS NULL" in sql
    assert "existing.clv_24h IS NULL" in sql
    assert "t.trade_timestamp <= now() - interval '24 hours'" in sql


def test_pending_paper_targets_keep_watchlist_exemption_and_skip_processed_trades() -> None:
    connection = RecordingConnection(
        results=[
            [
                SimpleNamespace(
                    condition_id="market-1",
                    token_id="token-1",
                    gamma_market_id=None,
                    trade_timestamp="2026-07-16T00:00:00Z",
                )
            ]
        ]
    )
    repository = WalletDataRepository(connection)  # type: ignore[arg-type]

    targets = repository.fetch_pending_paper_trade_targets(
        since="2026-07-16T00:00:00Z",  # type: ignore[arg-type]
        limit=10,
    )

    assert targets[0]["condition_id"] == "market-1"
    assert targets[0]["gamma_market_id"] == ""
    sql, params = connection.calls[0]
    assert "ww.wallet_address IS NOT NULL" in sql
    assert "ls.score >= 60 AND ls.confidence >= 0.35" in sql
    assert "s.signal_id IS NULL" in sql
    assert params["limit"] == 10


def test_signal_candidates_can_be_restricted_to_refreshed_tokens() -> None:
    connection = RecordingConnection()
    repository = PaperTradingRepository(connection)  # type: ignore[arg-type]

    assert (
        repository.fetch_signal_candidates(
            since="2026-07-16T00:00:00Z",  # type: ignore[arg-type]
            limit=500,
            token_ids=["paper-1", "paper-2"],
        )
        == []
    )

    sql, params = connection.calls[0]
    assert "t.token_id = ANY(CAST(:token_ids AS text[]))" in sql
    assert params["restrict_tokens"] is True
    assert params["token_ids"] == ["paper-1", "paper-2"]
