# PnL Engine and Reconciliation Report

Date: 2026-07-09

## Scope

Week04 adds a read-only PnL engine for wallet-market analysis. It consumes stored trades,
current positions, closed positions, and market status rows. It does not call order endpoints,
does not require signatures, and does not store trading credentials.

## Implemented

- Added schema tables:
  - `market_resolution_status`
  - `wallet_market_results`
  - `wallet_daily_equity`
  - `pnl_reconciliation_checks`
- Added pure PnL calculation logic in `backend.app.analytics.pnl_engine`.
- Added database runner and CLI:

```bash
python -m backend.scripts.calculate_pnl --wallet-limit 100
```

- Added wallet profile API:

```bash
GET /wallets/{wallet_address}/profile?market_limit=50
```

## PnL Policy

- `realized_pnl` is sourced from `wallet_positions_closed.realized_pnl`.
- `unrealized_pnl` is sourced from `wallet_positions_current.cash_pnl`.
- `current_value` is retained as exposure/mark value and is not included in realized PnL.
- Fee and slippage fields are present but estimated as zero in v1:
  - `estimated_fees`
  - `estimated_slippage`
  - `fees_estimated=true`
  - `slippage_estimated=true`
- Taker fee risk is marked only when raw trade fields identify the wallet as taker. The stored
  `/trades?takerOnly=false` request mode is not treated as trade role evidence.

## Aggregations

`wallet_market_results` stores one row per wallet, condition, token, and outcome. It includes:

- total buy/sell size and notional
- average buy/sell price
- open size and current value
- realized and unrealized PnL
- capital deployed and ROI
- entry/exit time and holding duration
- result status and outcome correctness when enough source evidence exists

`wallet_daily_equity` stores a v1 UTC-date curve:

- cumulative realized PnL by closed-position date
- current unrealized PnL on calculation date
- daily volume and trade count
- drawdown and max drawdown

## Reconciliation

`pnl_reconciliation_checks` starts with closed-position realized PnL checks. For each sampled
wallet-market-token, the engine value is compared with the source closed-position sum.

Difference categories reserved for reporting:

- `matched`
- `field_missing`
- `time_window_different`
- `fee_basis_different`
- `mapping_failed`
- `unknown`

## Validation

Unit tests cover:

- current `cash_pnl/current_value` does not enter realized PnL
- closed positions drive realized PnL and reconciliation
- average buy/sell price, ROI, profit factor, win rate, and concentration summary

Expected verification commands:

```bash
pytest -q
ruff check .
```

Local Week04 smoke:

```text
python -m backend.scripts.db_migrate
Applied schema migration: 2026_07_09_week04_pnl_schema_v1

python -m backend.scripts.calculate_pnl --wallet-limit 100 --profile-limit 3
wallets_processed: 100
failed_wallets: 0
market_statuses_refreshed: 500
wallet_market_results: 16181
wallet_daily_equity_rows: 4637
reconciliation_checks: 2703
```

## Known Limits

- V1 does not use order book depth for slippage. Week05 should fill this using archived price and
  book data.
- V1 does not infer maker/taker role from the endpoint-level `takerOnly` parameter.
- `outcome_correct` is only set when closed-position source price evidence is strong enough.
- Daily equity is date-level and not tick-level.
