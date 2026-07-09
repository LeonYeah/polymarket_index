# Polymarket Wallet Tracker - 项目交接

更新时间：2026-07-09

下次新会话先读本文件，再读 `../polymarket-wallet-tracker-plan/Week05-价格与订单簿归档.md`。当前主线是完成 Week05 的正式 100 市场与 24 小时归档验收，然后进入 Week06。

## 目标与边界

目标：建设一个可复现、可审计、可回测的 Polymarket 优质钱包研究系统，用公开只读数据完成市场、钱包、交易、仓位、容量、PnL、评分和后续跟单研究。

硬边界：

- 只做公开只读采集、建模、分析和回测。
- 不做真实下单，不保存私钥、签名凭证、交易 cookie、交易 API key。
- USA VPS 只作为公开只读 API 探针/采集节点，不作为真实订单执行节点。
- 未结算浮盈不得计入 realized PnL；`cashPnl/currentValue` 必须与 `realizedPnl` 分离。

## 环境与仓库

- 本地仓库：`/home/lee/workspace/search/codes`
- 周计划：`/home/lee/workspace/search/polymarket-wallet-tracker-plan`
- Python venv：`codes/.venv`
- VPS 登录：`ssh usa`
- 最新阶段：Week05 价格与订单簿归档基础闭环已实现，具体提交以 `git log --oneline -5` 为准。
- VPS 状态：`/home/lee/workspace/search/codes` 是空 Git 仓库，没有需要提交的代码。

## 当前架构

```text
codes/
  backend/
    app/
      analytics/            PnL 引擎与钱包画像聚合
      api/                  FastAPI: health、wallet timeline、wallet profile
      collectors/           Polymarket 只读 API 采集、市场数据、钱包回填、价格归档
      core/                 配置、日志、run_id
      db/                   PostgreSQL 连接、schema、repository
      domain/               领域模型草案
    scripts/
      api_probe.py          Gamma/Data/CLOB/WebSocket 只读探针
      db_migrate.py         schema 迁移
      ingest_market_data.py 市场、容量、holders 采集
      backfill_wallet_data.py 钱包发现、交易、仓位回填
      calculate_pnl.py      PnL 计算与 closed-position 对账
      archive_price_data.py 价格历史、订单簿、market WebSocket 归档
    tests/                  health、schema、解析、钱包回填、PnL、价格归档测试
  docs/
    api-probe-report.md
    market-data-ingestion-report.md
    wallet-backfill-report.md
    pnl-engine-report.md
    price-archive-report.md
    data-dictionary.md
  frontend/                 Next.js 占位，尚未开发 dashboard
  infra/                    Docker Compose: Postgres、Redis、backend
```

技术栈：Python、FastAPI、Pydantic、httpx、SQLAlchemy、psycopg、PostgreSQL、Docker Compose。当前未使用 TimescaleDB 特性。

## 已完成能力

基础工程：

- FastAPI 后端骨架、`/health`、配置系统、结构化日志、run_id。
- Docker Compose 可启动 PostgreSQL、Redis、backend。
- `.env.example` 不含私密凭证。

只读 API 验证：

- 已验证 Gamma、Data、CLOB HTTP 端点和 CLOB market WebSocket。
- 已确认 `/trades` 必须显式设置 `takerOnly=true/false`。
- 已保留 API 探针报告和脱敏样例：`docs/api-probe-report.md`、`docs/samples/`。

市场数据采集：

- 已建表：`ingestion_runs`、`events`、`markets`、`market_tokens`、`market_liquidity_snapshots`、`market_holders`、`raw_api_responses`。
- 已实现 Gamma keyset 分页、events/markets/token 映射、OI/live volume/liquidity/holders 入库、raw response 归档。
- 金额、价格、size 使用 `Decimal`；CLOB token id 按字符串处理；时间统一 UTC。
- 验收数据：`markets=500`、`tokens=1000`、`events=228`、`holders=2500+`、`liquidity_snapshots=526`、token mapping failures 为 0。

钱包发现与历史回填：

- 已建表：`wallets`、`wallet_candidates`、`trades`、`wallet_positions_current`、`wallet_positions_closed`、`wallet_activity_daily`、`wallet_backfill_checkpoints`。
- 候选来源覆盖 leaderboard DAY/WEEK/MONTH/ALL、market holders、近期 active traders。
- `/trades` 回填显式记录 `takerOnly=false`，无官方稳定 trade id 时用稳定字段生成 `trade_uid` 去重。
- 当前仓位和已平仓仓位分表保存，`realizedPnl` 与 `cashPnl/currentValue` 分离。
- checkpoint 支持 wallet、endpoint、takerOnly、offset 续跑；单钱包失败不影响整批。
- API：`GET /wallets/{wallet_address}/timeline`。
- Week03 验收数据：`wallet_candidates=1358` distinct wallets、完整回填钱包 320、trade-exhausted 钱包 108、唯一 trades 234957、current positions 15513、closed positions 14142、failed wallets 0。

PnL 引擎与对账：

- 已建表：`market_resolution_status`、`wallet_market_results`、`wallet_daily_equity`、`pnl_reconciliation_checks`。
- 已实现 PnL Engine v1，按 wallet/condition/token/outcome 聚合交易、当前仓位和已平仓仓位。
- `realized_pnl` 仅来自 `wallet_positions_closed.realized_pnl`。
- `unrealized_pnl` 来自 `wallet_positions_current.cash_pnl`；`current_value` 只作为敞口/估值字段。
- fee/slippage 字段已预留，v1 为显式 estimated zero，等待 Week05 用订单簿补充。
- API：`GET /wallets/{wallet_address}/profile?market_limit=50`。
- CLI：`python -m backend.scripts.calculate_pnl --wallet-limit 100`。
- Week04 验收数据：处理钱包 100、失败 0、`wallet_market_results=16181`、`wallet_daily_equity_rows=4637`、`reconciliation_checks=2703`。
- 当前验证：`pytest -q` 为 27 passed、1 warning；`ruff check .` 通过。

价格与订单簿归档：

- 已建表：`price_points`、`orderbook_snapshots`、`orderbook_top`、`orderbook_depth_snapshots`、`market_stream_events`。
- 已实现 CLOB `prices-history` 回填、`book` 快照归档、market WebSocket 短时归档。
- 订单簿归档拆出 best_bid、best_ask、midpoint、spread、spread_bps、top depth、有限档深度。
- WebSocket 事件同时保留 `received_at` 与 payload 原始事件时间 `event_at`，raw payload 入库。
- 已实现 CLV 基础函数，按 BUY/SELL 调整符号；已实现保守订单簿滑点估算函数。
- CLI：`python -m backend.scripts.archive_price_data --token-limit 100`。
- Week05 smoke：1 token 写入 `price_points=1440`、`orderbook_snapshots=1`、`orderbook_depth_snapshots=6`；2 秒 WebSocket 写入 `market_stream_events=1`。

## 关键口径

- `/trades?takerOnly=false` 是采集口径，不是单笔 maker/taker 角色证据。
- maker/taker 双侧归因尚未建模。
- 高活跃钱包可能仍有更深 `/trades` 历史，可从 `wallet_backfill_checkpoints` 续跑。
- `data/live-volume` 的 `id` 是 Gamma market 数值型 `id`，不是 `condition_id` 或 CLOB token id。
- `data/live-volume` 可能返回不在当前 market 批次里的 condition_id，容量快照表不强制 FK 到 `markets`。
- token 映射按 `clobTokenIds` 与 `outcomes` 顺序建立；长度不一致标记 `mapping_status=failed`。
- 不要用最后成交价替代可成交价格；Week05 应使用订单簿、spread、depth 做估算。
- `prices-history` 不是历史完整订单簿，不能据此声称精确模拟滑点。
- `market_stream_events.received_at` 是延迟估算主时间；payload `event_at` 可能乱序或延迟。

## 未完成与债务

下一阶段主线：

- Week05 基础代码已实现，但尚未完成 100 个活跃市场价格历史正式回填验收。
- 尚未完成 watchlist 市场 24 小时连续订单簿/WebSocket 归档验收。
- CLV 目前是基础函数，尚未批量物化到 Week03/Week04 历史交易。
- 尚未把 Week05 订单簿滑点、spread/depth 接入 PnL enrichment 和容量分析。

分析能力：

- SmartScore 尚未实现。
- 统计回测尚未实现。
- 纸面跟单、风控、人工确认、受控自动执行试运行尚未实现。
- 负风险、组合型市场、多 outcome 市场仅保留扩展空间，尚未深入建模。

数据与模型：

- Gamma active market 响应缺失稳定 category/tag；当前策略是缺失分类则保留并告警，后续需通过 event/tag 详情或其他来源补全。
- raw API response 已归档，但 market、event、trade、position、holder、orderbook 的 schema/contract 测试还不够细。
- closed positions 当前作为 realized PnL 权威输入；若 Data API 口径变化，需要通过对账报告识别差异。
- Daily equity v1 是 UTC 日期级，不是 tick 级净值。
- `outcome_correct` 只有在 closed position 的 `cur_price` 证据足够强时才设置，否则保持 null。

产品与生产化：

- frontend 仍是 Next.js 占位，未开发 dashboard。
- API 目前只有 health、wallet timeline、wallet profile，尚无完整 Dashboard 查询 API。
- 尚未做调度器、任务队列、长期限流策略、监控告警、部署脚本。
- VPS 尚未部署采集节点；部署时仍必须保持只读边界。

## 常用命令

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate

# 验证
pytest -q
ruff check .

# 数据库
docker compose -f infra/docker-compose.yml up -d postgres
python -m backend.scripts.db_migrate

# 市场采集 smoke
python -m backend.scripts.ingest_market_data --max-markets 5 --page-limit 5 --holders-market-limit 2 --holders-limit 3

# 钱包回填 smoke
python -m backend.scripts.backfill_wallet_data --candidate-limit 5 --leaderboard-limit 3 --holder-candidate-limit 3 --active-trader-limit 3 --backfill-wallet-limit 1 --page-limit 2 --max-trade-pages 1

# PnL smoke
python -m backend.scripts.calculate_pnl --wallet-limit 5 --profile-limit 2

# 价格与订单簿 smoke
python -m backend.scripts.archive_price_data --tokens <clob_token_id> --token-limit 1 --depth-limit 3
python -m backend.scripts.archive_price_data --tokens <clob_token_id> --skip-history --skip-orderbook --websocket --websocket-seconds 2 --websocket-event-limit 2

# API
uvicorn backend.app.main:app --reload
curl http://127.0.0.1:8000/health
curl 'http://127.0.0.1:8000/wallets/<wallet_address>/timeline?limit=100'
curl 'http://127.0.0.1:8000/wallets/<wallet_address>/profile?market_limit=50'

# 关闭本地服务
docker compose -f infra/docker-compose.yml down
```

## 下一步建议

完成 Week05 正式验收并准备进入 Week06。

建议顺序：

1. 跑 `python -m backend.scripts.archive_price_data --token-limit 100`，完成 100 token 价格历史正式回填。
2. 对 watchlist 跑较长时间 `--websocket` 和订单簿快照归档，记录断线/重连情况。
3. 为历史 trades 增加 CLV 批量物化 job 或查询 API。
4. 将订单簿滑点和 spread/depth 接入 PnL v1 的 `estimated_slippage` 或画像 enrichment。
5. 验收通过后进入 Week06：SmartScore 与统计回测。

下次会话可直接提示：

```text
请先阅读 codes/introduction.md 和 polymarket-wallet-tracker-plan/Week05-价格与订单簿归档.md。
当前 Week01-Week04 已完成；Week05 已实现价格历史、订单簿、WebSocket 归档基础闭环和 CLV/滑点基础函数，但尚未完成 100 token 与 24 小时连续归档正式验收。
请继续完成 Week05 验收或准备 Week06 SmartScore 与统计回测。保持只读边界，不要加入私钥、签名、真实下单或交易凭证。
```
