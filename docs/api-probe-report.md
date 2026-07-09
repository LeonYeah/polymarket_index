# API Probe Report

## Scope

Week01 validates only read-only public endpoints. No private keys, cookies, signatures, or order endpoints are used.

## Environment

- Local code path: `/home/lee/workspace/search/codes`
- VPS probe path: `/home/lee/workspace/search/codes`
- Gamma base URL: `https://gamma-api.polymarket.com`
- Data base URL: `https://data-api.polymarket.com`
- CLOB base URL: `https://clob.polymarket.com`
- WebSocket base URL: `wss://ws-subscriptions-clob.polymarket.com/ws`

## Probe Coverage

| Source | Endpoint | Case types |
|---|---|---|
| Gamma | `/markets/keyset` | normal, empty, invalid parameter |
| Gamma | `/events/keyset` | normal |
| Data | `/v1/leaderboard` | normal |
| Data | `/holders` | normal with discovered market |
| Data | `/positions` | normal with discovered wallet, invalid wallet |
| Data | `/closed-positions` | normal with discovered wallet |
| Data | `/trades` | `takerOnly=true`, `takerOnly=false`, empty wallet |
| Data | `/oi` | normal |
| Data | `/live-volume` | normal |
| CLOB | `/book` | normal with discovered token, invalid token |
| CLOB | `/prices-history` | normal with discovered token |
| CLOB | `/markets/{condition_id}` | normal with discovered condition id |
| WebSocket | `/market` | subscribe to discovered token |

## Operational Findings

- Every probe run emits a `run_id` and writes sanitized JSON samples under `docs/samples`.
- `/trades` must always set `takerOnly` explicitly. Comparing `true` and `false` is part of every probe run because relying on defaults can undercount maker-style wallets.
- Token IDs can exceed JavaScript integer precision and must be handled as strings.
- Decimal money/price/size fields must not be stored as binary floats.
- Time fields must be normalized to UTC during ingestion; endpoint-specific units should be recorded from observed samples.
- VPS probe on 2026-07-09T02:01Z confirmed Gamma, Data, CLOB, and market WebSocket read-only access from `usa`.
- `data.live-volume` requires an integer Gamma market `id`; condition IDs and token IDs are rejected.
- `data.positions` with `user=not-a-wallet` returned `400`; invalid/empty-result probes must distinguish malformed identifiers from valid addresses with no data.
- CLOB WebSocket timestamps were observed as millisecond strings in the first market snapshot.

## 2026-07-09 VPS Probe Result

| Endpoint | Result |
|---|---|
| Gamma `/markets/keyset` | `200`, 5 markets, keyset cursor present |
| Gamma `/events/keyset` | `200`, 5 events, keyset cursor present |
| Gamma empty query | `200`, empty market list |
| Gamma invalid limit | `422`, validation error |
| Data `/trades?takerOnly=false` | `200`, 10 trades |
| Data `/trades?takerOnly=true` | `200`, 10 trades |
| Data `/v1/leaderboard` | `200`, 10 rows |
| Data `/holders` | `200`, 2 rows for discovered market |
| Data `/positions` | `200`, 6 rows for discovered wallet |
| Data `/closed-positions` | `200`, 10 rows for discovered wallet |
| Data empty wallet trades | `200`, empty list |
| Data invalid wallet positions | `400`, malformed user parameter |
| Data `/oi` | `200`, 1 row |
| Data `/live-volume` | `200` when called with Gamma market `id` |
| CLOB `/book` | `200`, order book fields present |
| CLOB `/prices-history` | `200`, `history` field present |
| CLOB `/markets/{condition_id}` | `200`, market metadata fields present |
| CLOB invalid `/book` | `404`, no orderbook for token |
| WebSocket `/ws/market` | `101` handshake, received initial orderbook snapshot |

## VPS Boundary

The USA VPS is allowed to run read-only API probes and later collectors. It must not store private keys, signing material, trading cookies, or order API credentials. It must not run order execution from the current US region without a fresh legal/geoblock boundary test.

## How To Reproduce

```bash
cd /home/lee/workspace/search/codes
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[probe]"
python -m backend.scripts.api_probe --output-dir docs/samples
```

Add the generated summary path and notable failures to this report after each run.

