# Polymarket Wallet Tracker

Read-only Polymarket wallet research system covering market ingestion, wallet backfill,
PnL reconciliation, price/order book archiving, SmartScore, alerts, and paper copy-trading.

## Layout

- `backend/`: FastAPI service, configuration, API probe, collectors, analytics, and CLIs.
- `frontend/`: Next.js research dashboard, wallet/market detail, alerts, and paper trading.
- `infra/`: local Docker Compose for Postgres, Redis, and backend.
- `docs/`: ADRs, data dictionary, API probe report, and sanitized samples.

## Local backend

```bash
cd codes
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,probe]"
uvicorn backend.app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Wallet PnL profile after Week04 calculation:

```bash
python -m backend.scripts.calculate_pnl --wallet-limit 100
curl 'http://127.0.0.1:8000/wallets/<wallet_address>/profile?market_limit=50'
```

Price and order book archive after Week05 schema migration:

```bash
python -m backend.scripts.archive_price_data --token-limit 100
python -m backend.scripts.archive_price_data --tokens <clob_token_id> --token-limit 1 --depth-limit 3
python -m backend.scripts.archive_price_data --tokens <clob_token_id> --skip-history --skip-orderbook --websocket --websocket-seconds 30
python -m backend.scripts.archive_price_data --skip-history --skip-orderbook --calculate-clv --clv-limit 1000
```

SmartScore ranking and statistical backtest after Week06 schema migration:

```bash
python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20
python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20 --backtest --strategy-size 10 --validation-days 30
curl 'http://127.0.0.1:8000/scores/leaderboard?limit=50'
```

Paper copy-trading after Week08 schema migration:

```bash
python -m backend.scripts.db_migrate
python -m backend.scripts.run_paper_trading --lookback-minutes 60 --order-type FAK
curl 'http://127.0.0.1:8000/paper/summary'
curl 'http://127.0.0.1:8000/paper/orders?limit=100'
```

For continuous sampling, run under a process supervisor. The loop records each cycle independently
and never sends a real order:

```bash
python -m backend.scripts.run_paper_trading \
  --lookback-minutes 10 \
  --repeat-seconds 60 \
  --max-cycles 0
```

The production sampling loop runs on the USA VPS with native PostgreSQL and systemd. It is not
publicly exposed. See `docs/vps-sampling-runbook.md` for service operations, SSH tunneling,
health checks, backups, and the seven-day acceptance window.

For a 24-hour watchlist archive, run with explicit watchlist tokens:

```bash
python -m backend.scripts.archive_price_data \
  --tokens <comma_separated_watchlist_tokens> \
  --skip-history \
  --orderbook-cycles 2880 \
  --orderbook-interval-seconds 30 \
  --websocket \
  --websocket-seconds 86400 \
  --websocket-event-limit 1000000
```

Run the read-only API probe:

```bash
python -m backend.scripts.api_probe --output-dir docs/samples
```

The probe writes sanitized JSON samples and a structured run summary. It does not
use private keys, cookies, signing credentials, or order endpoints.

## Market data ingestion

Apply the PostgreSQL schema and run a bounded read-only market ingestion:

```bash
python -m backend.scripts.db_migrate
python -m backend.scripts.ingest_market_data --max-markets 500
```

For a smoke test, keep the run small:

```bash
python -m backend.scripts.ingest_market_data --max-markets 5 --page-limit 5 --holders-market-limit 2 --holders-limit 3
```

Useful controls:

```bash
python -m backend.scripts.ingest_market_data \
  --max-markets 500 \
  --categories Politics,Finance,Tech \
  --token-verification-limit 100
```

When Gamma omits category fields, the worker keeps those markets and records an ingestion warning
instead of silently dropping the batch.
