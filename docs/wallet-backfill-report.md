# Wallet Discovery and Backfill Report

Date: 2026-07-09

## Scope

Week03 adds read-only wallet discovery and historical behavior backfill. No private keys,
cookies, signatures, or order endpoints are used.

## Implemented

- Added schema tables:
  - `wallets`
  - `wallet_candidates`
  - `trades`
  - `wallet_positions_current`
  - `wallet_positions_closed`
  - `wallet_activity_daily`
  - `wallet_backfill_checkpoints`
- Added `python -m backend.scripts.backfill_wallet_data`.
- Candidate sources:
  - `/v1/leaderboard` with `DAY`, `WEEK`, `MONTH`, `ALL` periods.
  - Existing `market_holders` rows from Week02.
  - Recent `/trades?takerOnly=false` rows.
- Trade backfill:
  - Calls `/trades` with explicit `takerOnly=false`.
  - Stores `proxyWallet`, `conditionId`, `asset`, `side`, `price`, `size`, `timestamp`,
    `transactionHash`, and normalized notional.
  - Generates `trade_uid` from stable trade fields when the API has no trade id.
  - Stores offset checkpoints for paged resume.
- Position backfill:
  - Stores `/positions` current positions separately from `/closed-positions`.
  - Keeps `realizedPnl` separate from `cashPnl/currentValue`.
- Activity stats:
  - Populates wallet-level first/last seen, active days, market counts, resolved market counts,
    and 30/90/180 day notional windows from stored trades.

## Smoke Test

Command:

```bash
python -m backend.scripts.backfill_wallet_data \
  --candidate-limit 5 \
  --leaderboard-limit 3 \
  --holder-candidate-limit 3 \
  --active-trader-limit 3 \
  --backfill-wallet-limit 1 \
  --page-limit 2 \
  --max-trade-pages 1
```

Result:

```text
status: succeeded
wallets: 18 attempted writes, 9 distinct wallets in smoke DB
candidates: 18
wallets_backfilled: 1
trades: 2
current_positions: 2
closed_positions: 2
checkpoints: 3
raw_responses: 8
```

Database count check:

```text
wallets: 9
wallet_candidates: 18
trades: 2
wallet_positions_current: 2
wallet_positions_closed: 2
wallet_backfill_checkpoints: 3
```

## Validation

```text
python -m backend.scripts.db_migrate
Applied schema migration: 2026_07_09_week03_schema_v1

pytest -q
20 passed, 1 warning

ruff check .
All checks passed
```

## Remaining Week03 Acceptance Work

- Run a full or staged production-sized backfill to reach at least 500 distinct candidate wallets.
- Backfill at least 100 wallets with trades, current positions, and closed positions.
- Add rate-limit/backoff handling before increasing wallet volume materially.
- Add richer query/API endpoints for wallet timelines after the backfill tables are populated.
