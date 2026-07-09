from functools import lru_cache

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://polymarket:polymarket@localhost:5432/polymarket"
    redis_url: str = "redis://localhost:6379/0"

    polymarket_gamma_base_url: AnyUrl = Field(
        default="https://gamma-api.polymarket.com",
        description="Read-only Gamma API base URL.",
    )
    polymarket_data_base_url: AnyUrl = Field(
        default="https://data-api.polymarket.com",
        description="Read-only Data API base URL.",
    )
    polymarket_clob_base_url: AnyUrl = Field(
        default="https://clob.polymarket.com",
        description="Read-only CLOB API base URL.",
    )
    polymarket_ws_base_url: AnyUrl = "wss://ws-subscriptions-clob.polymarket.com/ws"

    api_probe_timeout_seconds: float = 20.0
    api_probe_output_dir: str = "docs/samples"

    market_ingestion_page_limit: int = 100
    market_ingestion_max_markets: int = 500
    market_ingestion_holders_market_limit: int = 25
    market_ingestion_holders_limit: int = 50
    market_ingestion_target_categories: str = "Politics,Finance,Tech"
    market_ingestion_token_verification_limit: int = 100

    wallet_candidate_limit: int = 500
    wallet_leaderboard_limit: int = 150
    wallet_holder_candidate_limit: int = 250
    wallet_active_trader_limit: int = 500
    wallet_backfill_wallet_limit: int = 100
    wallet_backfill_page_limit: int = 100
    wallet_backfill_max_trade_pages: int = 10
    wallet_backfill_retry_attempts: int = 3
    wallet_backfill_retry_base_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
