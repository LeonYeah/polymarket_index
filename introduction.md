# Polymarket Wallet Tracker - 快速交接

更新时间：2026-07-09

下次新会话先读本文件，再读 `../polymarket-wallet-tracker-plan/Week07-API-Dashboard与提醒.md`。当前主线可进入 Week07：补 Dashboard/API 与提醒能力。若排行榜高置信钱包为空，优先展示 failed gate 原因，不要隐藏数据。

## 项目目标与边界

建设一个可复现、可审计、可回测的 Polymarket 优质钱包研究系统，用公开只读数据完成钱包发现、市场行为分析、PnL、CLV、SmartScore、回测和后续纸面跟单研究。

硬边界：

- 只做公开只读采集、建模、分析和回测。
- 不做真实下单，不保存私钥、签名凭证、交易 cookie、交易 API key。
- USA VPS 只作为公开只读 API 探针/采集节点，不作为真实订单执行节点。
- 未结算浮盈不得计入 realized PnL；`cashPnl/currentValue` 必须与 `realizedPnl` 分离。

## 环境与状态

- 本地仓库：`/home/lee/workspace/search/codes`
- 周计划：`/home/lee/workspace/search/polymarket-wallet-tracker-plan`
- Python venv：`/home/lee/workspace/search/codes/.venv`
- VPS 登录：`ssh usa`
- 最新阶段：Week01-Week06 已完成工程闭环，最新提交以 `git log --oneline -5` 为准。
- VPS 状态：`/home/lee/workspace/search/codes` 是空 Git 仓库，目前没有需要提交的代码。
- 当前验证：`pytest -q` 为 46 passed、1 warning；`ruff check .` 通过。

## 当前架构

```text
codes/
  backend/
    app/
      collectors/   Polymarket 只读 API、市场、钱包、价格、订单簿、WebSocket 采集
      analytics/    PnL 引擎、钱包画像、SmartScore、统计回测
      db/           PostgreSQL schema、repository、迁移
      api/          health、wallet timeline/profile、score leaderboard
      core/         配置、日志、run_id
    scripts/
      api_probe.py
      db_migrate.py
      ingest_market_data.py
      backfill_wallet_data.py
      calculate_pnl.py
      archive_price_data.py
      score_wallets.py
    tests/          schema、采集归一化、钱包回填、PnL、价格归档、SmartScore
  docs/             API/采集/PnL/价格归档/SmartScore 报告、数据字典、样例
  frontend/         Next.js 占位，尚未开发 dashboard
  infra/            Docker Compose: Postgres、Redis、backend
```

技术栈：Python、FastAPI、Pydantic、httpx、SQLAlchemy、psycopg、PostgreSQL、Docker Compose。当前未使用 TimescaleDB 特性。

## 已完成能力

基础工程：

- FastAPI 后端骨架、`/health`、配置系统、结构化日志、run_id。
- Docker Compose 可启动 Postgres、Redis、backend。
- `.env.example` 不含私密凭证，已覆盖市场、钱包、价格归档配置。
- 数据库迁移集中在 `backend/app/db/migrations.py`，当前 schema 到 Week06。

只读 API 与市场数据：

- 已验证 Gamma、Data、CLOB HTTP 端点和 CLOB market WebSocket。
- 已实现 Gamma keyset 分页、events/markets/token 映射、OI/live volume/liquidity/holders 入库、raw response 归档。
- CLOB token id 按字符串处理；金额、价格、size 使用 `Decimal`；时间统一 UTC。
- 关键报告：`docs/api-probe-report.md`、`docs/market-data-ingestion-report.md`。

钱包发现与历史回填：

- 已实现候选钱包发现：leaderboard、market holders、近期 active traders。
- 已实现交易、当前仓位、已平仓仓位回填；`/trades` 显式使用 `takerOnly=false`。
- 无官方稳定 trade id 时，用稳定字段生成 `trade_uid` 去重。
- checkpoint 支持按 wallet/endpoint/takerOnly/offset 续跑；单钱包失败不影响整批。
- API：`GET /wallets/{wallet_address}/timeline`。
- 关键报告：`docs/wallet-backfill-report.md`。

PnL 与钱包画像：

- 已实现 PnL Engine v1，按 wallet/condition/token/outcome 聚合交易、当前仓位、已平仓仓位。
- `realized_pnl` 只来自 `wallet_positions_closed.realized_pnl`。
- `unrealized_pnl` 来自 `wallet_positions_current.cash_pnl`；`current_value` 只做敞口/估值字段。
- 已生成 `wallet_market_results`、`wallet_daily_equity`、`pnl_reconciliation_checks`。
- API：`GET /wallets/{wallet_address}/profile?market_limit=50`。
- CLI：`python -m backend.scripts.calculate_pnl --wallet-limit 100`。
- 关键报告：`docs/pnl-engine-report.md`。

价格、订单簿、CLV 与可跟随性：

- 已实现 CLOB `prices-history` 回填、`book` 快照归档、market WebSocket 归档、多轮订单簿循环采样。
- 已拆分 top-of-book、有限档深度、spread、spread bps、top depth、midpoint。
- WebSocket 事件同时保留系统 `received_at` 和 payload `event_at`。
- 已实现 signed CLV：`clv_30s`、`clv_2m`、`clv_10m`、`clv_1h`、`clv_24h`。
- 已实现保守滑点估算、depth/spread 缺陷识别、`market_liquidity_score`。
- CLI：`python -m backend.scripts.archive_price_data ...`。
- 关键报告：`docs/price-archive-report.md`。

SmartScore 与统计回测：

- 已实现 Feature Engine v1、SmartScore v1、硬门槛、惩罚项、confidence 和组件拆解。
- 已落库版本化表：`wallet_features`、`wallet_scores`、`wallet_score_components`、`backtest_runs`、`backtest_wallet_results`。
- 评分组件：收益质量、预测质量、时机优势、稳定性、可跟随性、网络信号占位。
- 硬门槛：resolved 数、活跃天数、realized notional、ROI、Bayesian win rate、最大回撤、单市场集中度、可跟随性。
- 回测 v1 比较三类策略：`top_score`、`top_pnl`、`random_active`。
- API：`GET /scores/leaderboard?limit=50&high_confidence_only=false`。
- CLI：`python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20 --backtest`。
- 关键报告：`docs/smart-score-report.md`。

## 关键口径

- `/trades?takerOnly=false` 是采集口径，不是单笔 maker/taker 角色证据。
- maker/taker 双侧归因尚未建模。
- 高活跃钱包可能仍有更深 `/trades` 历史，可从 `wallet_backfill_checkpoints` 续跑。
- `data/live-volume` 的 `id` 是 Gamma market 数值型 `id`，不是 `condition_id` 或 CLOB token id。
- token 映射按 `clobTokenIds` 与 `outcomes` 顺序建立；长度不一致标记 `mapping_status=failed`。
- 不要用最后成交价替代可成交价格；滑点和可跟随性必须优先使用订单簿、spread、depth。
- `prices-history` 不是历史订单簿，不能据此声称精确模拟滑点。
- `market_stream_events.received_at` 是延迟估算主时间；payload `event_at` 可能乱序或延迟。
- SmartScore 是研究指标，不是收益承诺。

## 未完成与债务

当前主线：

- Week07 Dashboard 与提醒尚未实现。
- 前端仍是 Next.js 占位，没有可用 dashboard。
- Dashboard API 仍不完整：缺评分组件详情、回测摘要、市场/钱包聚合查询、提醒查询。

数据与分析债务：

- Week05 的 24 小时 watchlist 订单簿/WebSocket 长跑命令已具备，但尚未实际跑满 24 小时。
- `avg_followability` 依赖订单簿归档覆盖；未归档 token 会被保守评低，可能导致高质量钱包无法进入高置信榜。
- Week04 PnL 的 `estimated_slippage` 尚未用 Week05 订单簿数据回写。
- 回测 v1 依赖当前已落库历史结果做近似时间切分；严格历史重放需要更完整的历史状态快照。
- SmartScore 网络信号仍为中性占位；资金来源、协同行为留到 Week11 链上索引与钱包聚类。
- maker/taker 双侧钱包归因尚未处理。
- 负风险、组合型市场、多 outcome 市场仅保留扩展空间，尚未深入建模。
- Gamma active market 响应缺少稳定 category/tag 时，目前是保留并告警，后续需补全分类来源。
- raw API response 已归档，但 market、event、trade、position、holder、orderbook 的 schema/contract 测试还不够细。
- `outcome_correct` 只有在 closed position 的 `cur_price` 证据足够强时才设置，否则保持 null。
- Daily equity v1 是 UTC 日期级，不是 tick 级净值。

生产化债务：

- 尚未做调度器、任务队列、长期限流策略、监控告警、部署脚本。
- VPS 尚未部署正式采集节点。
- 纸面跟单、风控、人工确认、受控自动执行试运行均未实现。

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

# 价格、订单簿、CLV
python -m backend.scripts.archive_price_data --token-limit 100 --skip-orderbook
python -m backend.scripts.archive_price_data --token-limit 5 --skip-history --orderbook-cycles 3 --orderbook-interval-seconds 2 --depth-limit 5 --websocket --websocket-seconds 10 --websocket-event-limit 10
python -m backend.scripts.archive_price_data --skip-history --skip-orderbook --calculate-clv --clv-limit 1000

# SmartScore 与回测
python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20
python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20 --backtest --strategy-size 10 --validation-days 30

# API
uvicorn backend.app.main:app --reload
curl http://127.0.0.1:8000/health
curl 'http://127.0.0.1:8000/wallets/<wallet_address>/timeline?limit=100'
curl 'http://127.0.0.1:8000/wallets/<wallet_address>/profile?market_limit=50'
curl 'http://127.0.0.1:8000/scores/leaderboard?limit=50'
```

24 小时 watchlist 归档形态：

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

## 下一步建议

1. 阅读 `../polymarket-wallet-tracker-plan/Week07-API-Dashboard与提醒.md`。
2. 先补 Dashboard API：排行榜、评分组件拆解、回测摘要、钱包详情、提醒状态。
3. 再开发前端实际工具界面；不要做营销 landing page。
4. 排行榜若没有高置信钱包，展示 all-ranked、confidence、failed gates 和原因。
5. 若要提升评分质量，先补跑高价值 token 的订单簿/CLV，再扩大 `score_wallets --wallet-limit`。
6. 全程保持只读边界，不引入私钥、签名、真实下单或交易凭证。
