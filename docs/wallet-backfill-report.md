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
- Added `GET /wallets/{wallet_address}/timeline`.
- Added wallet-level HTTP retry/backoff for 429, 5xx, and transient network failures.
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

## Acceptance Backfill

Commands were run in staged batches to keep request volume observable:

```bash
python -m backend.scripts.backfill_wallet_data \
  --candidate-limit 500 \
  --leaderboard-limit 150 \
  --holder-candidate-limit 500 \
  --active-trader-limit 500 \
  --backfill-wallet-limit 100 \
  --page-limit 100 \
  --max-trade-pages 10
```

The final top-up batch used `--backfill-wallet-limit 20` after the first 300 wallets had been
covered.

Run summaries:

```text
wallet_backfill_20260709T060851Z_b8158328:
  distinct_candidate_wallets: 797
  fully_backfilled_wallets: 100
  failed_wallets: 0

wallet_backfill_20260709T062151Z_d7e51892:
  distinct_candidate_wallets: 1035
  fully_backfilled_wallets: 200
  trade_exhausted_wallets: 26
  failed_wallets: 0

wallet_backfill_20260709T063257Z_1ba9570a:
  distinct_candidate_wallets: 1223
  fully_backfilled_wallets: 300
  trade_exhausted_wallets: 91
  failed_wallets: 0

wallet_backfill_20260709T064001Z_328de340:
  distinct_candidate_wallets: 1358
  fully_backfilled_wallets: 320
  trade_exhausted_wallets: 108
  failed_wallets: 0
```

Final database counts:

```text
wallet_candidates distinct wallets: 1358
fully backfilled wallets: 320
trade-exhausted wallets: 108
trades: 234957
distinct trade_uid: 234957
trade wallets: 319
wallet_positions_current: 15513
wallet_positions_closed: 14142
wallet_activity_daily: 6557
```

Empty-position handling:

```text
fully backfilled wallets with no current positions: 8
fully backfilled wallets with no closed positions: 2
```

Checkpoint status:

```text
/closed-positions succeeded: 320
/positions succeeded: 320
/trades exhausted: 108
/trades running: 212
```

`/trades running` means the wallet reached the configured page cap and can be resumed from its
stored offset. The Week03 acceptance bar is satisfied by more than 100 wallets with all three
endpoint checkpoints, and more than 100 wallets whose trade history reached exhausted status.

## Idempotency Check

The same 20 trade rows were upserted twice for one wallet:

```text
rows_checked: 20
before: 234946
after_first: 234957
after_second: 234957
```

The first upsert added 11 newly observed rows from the live API response; the second identical
upsert added zero rows. The final table count equals `count(distinct trade_uid)`.

## Timeline API Check

`GET /wallets/0x016909bcb23f59f1022689742014f22d8691043c/timeline?limit=3`
returned:

```text
status_code: 200
trade_count: 3
first_trade_uid_present: true
```

## Validation

```text
python -m backend.scripts.db_migrate
Applied schema migration: 2026_07_09_week03_schema_v1

pytest -q
22 passed, 1 warning

ruff check .
All checks passed
```

## Remaining Follow-Up

- Maker/taker counterparty attribution is still a later modeling refinement. Week03 stores
  `takerOnly=false` explicitly to avoid the API default hiding maker-style rows.
- Some high-activity wallets still have `/trades` status `running`; they can be resumed from
  checkpoint offsets when deeper history is needed.
- Week04 should consume these tables for realized/unrealized PnL and reconciliation.
