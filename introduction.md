# Polymarket Wallet Tracker - 项目交接

更新时间：2026-07-09

下次新会话先读本文件，再读 `../polymarket-wallet-tracker-plan/Week07-API-Dashboard与提醒.md`。当前主线可进入 Week07；如需提升评分质量，可先补跑高价值 token 的 Week05 订单簿/CLV 归档。

## 项目目标

建设一个可复现、可审计、可回测的 Polymarket 优质钱包研究系统。当前系统只使用公开只读数据，已覆盖市场、钱包、交易、仓位、PnL、订单簿、CLV、可跟随性、SmartScore 和统计回测基础能力。

硬边界：

- 只做公开只读采集、建模、分析和回测。
- 不做真实下单，不保存私钥、签名凭证、交易 cookie、交易 API key。
- USA VPS 只作为公开只读 API 探针/采集节点，不作为真实订单执行节点。
- 未结算浮盈不得计入 realized PnL；`cashPnl/currentValue` 必须与 `realizedPnl` 分离。

## 环境与入口

- 本地仓库：`/home/lee/workspace/search/codes`
- 周计划：`/home/lee/workspace/search/polymarket-wallet-tracker-plan`
- Python venv：`codes/.venv`
- VPS 登录：`ssh usa`
- 最新阶段：Week06 SmartScore 与统计回测已完成工程闭环，具体提交以 `git log --oneline -5` 为准。
- VPS 状态：`/home/lee/workspace/search/codes` 是空 Git 仓库，没有需要提交的代码。

## 当前架构

```text
codes/
  backend/
    app/
      analytics/      PnL 引擎、钱包画像聚合、SmartScore/回测
      api/            FastAPI: health、wallet timeline、wallet profile、score leaderboard
      collectors/     市场采集、钱包回填、价格/订单簿/WebSocket 归档
      core/           配置、日志、run_id
      db/             PostgreSQL schema、repository、迁移
      domain/         领域模型草案
    scripts/
      api_probe.py            只读 API 探针
      db_migrate.py           schema 迁移
      ingest_market_data.py   市场、容量、holders 采集
      backfill_wallet_data.py 钱包发现、交易、仓位回填
      calculate_pnl.py        PnL 计算与 closed-position 对账
      archive_price_data.py   价格历史、订单簿、WebSocket、CLV 归档/物化
      score_wallets.py        SmartScore 排行榜与统计回测
    tests/            health、schema、解析、钱包回填、PnL、价格归档、SmartScore 测试
  docs/               API/采集/PnL/价格归档/SmartScore 报告、数据字典、样例
  frontend/           Next.js 占位，尚未开发 dashboard
  infra/              Docker Compose: Postgres、Redis、backend
```

技术栈：Python、FastAPI、Pydantic、httpx、SQLAlchemy、psycopg、PostgreSQL、Docker Compose。当前未使用 TimescaleDB 特性。

## 已完成能力

基础工程：

- FastAPI 后端骨架、`/health`、配置系统、结构化日志、run_id。
- Docker Compose 可启动 PostgreSQL、Redis、backend。
- `.env.example` 不含私密凭证，并已覆盖市场、钱包、价格归档相关配置。
- 当前验证：`pytest -q` 为 46 passed、1 warning；`ruff check .` 通过。

只读 API 与市场数据：

- 已验证 Gamma、Data、CLOB HTTP 端点和 CLOB market WebSocket。
- 已确认 `/trades` 必须显式设置 `takerOnly=true/false`。
- 已实现 Gamma keyset 分页、events/markets/token 映射、OI/live volume/liquidity/holders 入库、raw response 归档。
- 金额、价格、size 使用 `Decimal`；CLOB token id 按字符串处理；时间统一 UTC。
- 市场采集验收数据：`markets=500`、`tokens=1000`、`events=228`、`holders=2500+`、`liquidity_snapshots=526`、token mapping failures 为 0。

钱包发现与历史回填：

- 已建表：`wallets`、`wallet_candidates`、`trades`、`wallet_positions_current`、`wallet_positions_closed`、`wallet_activity_daily`、`wallet_backfill_checkpoints`。
- 候选来源覆盖 leaderboard DAY/WEEK/MONTH/ALL、market holders、近期 active traders。
- 交易回填显式使用 `/trades?takerOnly=false`；无官方稳定 trade id 时用稳定字段生成 `trade_uid` 去重。
- 当前仓位和已平仓仓位分表保存，`realizedPnl` 与 `cashPnl/currentValue` 分离。
- checkpoint 支持 wallet、endpoint、takerOnly、offset 续跑；单钱包失败不影响整批。
- API：`GET /wallets/{wallet_address}/timeline`。
- 钱包回填验收数据：`wallet_candidates=1358` distinct wallets、完整回填钱包 320、trade-exhausted 钱包 108、唯一 trades 234957、current positions 15513、closed positions 14142、failed wallets 0。

PnL 与画像：

- 已建表：`market_resolution_status`、`wallet_market_results`、`wallet_daily_equity`、`pnl_reconciliation_checks`。
- PnL Engine v1 按 wallet/condition/token/outcome 聚合交易、当前仓位和已平仓仓位。
- `realized_pnl` 仅来自 `wallet_positions_closed.realized_pnl`。
- `unrealized_pnl` 来自 `wallet_positions_current.cash_pnl`；`current_value` 只作为敞口/估值字段。
- fee/slippage 字段已预留，v1 为显式 estimated zero；后续可用 Week05 订单簿数据 enrichment。
- API：`GET /wallets/{wallet_address}/profile?market_limit=50`。
- CLI：`python -m backend.scripts.calculate_pnl --wallet-limit 100`。
- PnL 验收数据：处理钱包 100、失败 0、`wallet_market_results=16181`、`wallet_daily_equity_rows=4637`、`reconciliation_checks=2703`。

价格、订单簿、CLV：

- 已建表：`price_points`、`orderbook_snapshots`、`orderbook_top`、`orderbook_depth_snapshots`、`market_stream_events`、`market_followability_snapshots`、`trade_clv_metrics`。
- 已实现 CLOB `prices-history` 回填、`book` 快照归档、market WebSocket 归档、多轮订单簿循环采样。
- 订单簿归档拆出 best_bid、best_ask、midpoint、spread、spread_bps、top depth、有限档深度。
- WebSocket 事件保留 `received_at` 与 payload 原始事件时间 `event_at`，raw payload 入库。
- 已实现 CLV 基础函数和批量物化，按 BUY/SELL 调整符号。
- 已实现保守订单簿滑点估算、spread/depth 缺陷识别和 `market_liquidity_score`。
- CLI：`python -m backend.scripts.archive_price_data --token-limit 100`。
- Week05 验收数据：100 token 价格历史回填 `price_points=144101` attempted、失败 0；5 token/3 轮订单簿短连续归档 `orderbook_snapshots=15`、`orderbook_depth_snapshots=150`、`followability_snapshots=15`；10 秒 WebSocket 写入 `market_stream_events=10`、重连 0；CLV 物化 `trade_clv_metrics=200`，其中 19 条有至少一种非空 CLV。

SmartScore 与统计回测：

- 已建表：`wallet_features`、`wallet_scores`、`wallet_score_components`、`backtest_runs`、`backtest_wallet_results`。
- SmartScore v1 使用可解释规则分，组件为收益质量、预测质量、时机优势、稳定性、可跟随性、网络信号占位。
- 硬门槛覆盖 resolved 数、活跃天数、realized notional、ROI、Bayesian win rate、最大回撤、单市场集中度、可跟随性。
- 惩罚项覆盖小样本封顶、单市场暴利扣分、低流动性占比扣分，未结算浮盈占比降低 confidence。
- API：`GET /scores/leaderboard?limit=50&high_confidence_only=false`。
- CLI：`python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20 --backtest`。
- Week06 smoke：schema 迁移 `2026_07_09_week06_smart_score_schema_v1`；`feature_rows=5`、`scores=5`、`leaderboard_rows=5`、`backtest_wallet_results=6`；三策略覆盖 `top_score`、`top_pnl`、`random_active`。

## 关键口径

- `/trades?takerOnly=false` 是采集口径，不是单笔 maker/taker 角色证据。
- maker/taker 双侧归因尚未建模。
- 高活跃钱包可能仍有更深 `/trades` 历史，可从 `wallet_backfill_checkpoints` 续跑。
- `data/live-volume` 的 `id` 是 Gamma market 数值型 `id`，不是 `condition_id` 或 CLOB token id。
- `data/live-volume` 可能返回不在当前 market 批次里的 condition_id，容量快照表不强制 FK 到 `markets`。
- token 映射按 `clobTokenIds` 与 `outcomes` 顺序建立；长度不一致标记 `mapping_status=failed`。
- 不要用最后成交价替代可成交价格；滑点与可跟随性应使用订单簿、spread、depth。
- `prices-history` 不是历史完整订单簿，不能据此声称精确模拟滑点。
- `market_stream_events.received_at` 是延迟估算主时间；payload `event_at` 可能乱序或延迟。

## 未完成与债务

下一阶段主线：

- Week07 Dashboard 与提醒尚未实现。
- Dashboard 查询 API 目前只有钱包 timeline/profile 与 score leaderboard，还缺少适合前端聚合展示的市场、评分组件、回测报告 API。
- 当前 smoke 样本没有高置信钱包，主要原因是 followability 数据覆盖不足或样本量/活跃天数门槛不足。
- 回测 v1 依赖当前已落库历史结果近似时间切分；若要严格历史重放，需要更完整的历史状态快照。

数据与分析债务：

- Week05 的 24 小时 watchlist 长跑命令形态已具备，但当前只做了短连续验收，没有实际等待完整 24 小时。
- Week05 订单簿滑点、spread/depth 尚未回写到 Week04 PnL 的 `estimated_slippage`；Week06 可先直接读取 `trade_clv_metrics` 和 `market_followability_snapshots`。
- SmartScore 网络信号仍为中性占位，资金来源和协同行为留到 Week11 链上索引与钱包聚类。
- `avg_followability` 依赖 Week05 订单簿归档覆盖，未归档 token 会被保守评低。
- maker/taker 双侧钱包归因尚未处理。
- 负风险、组合型市场、多 outcome 市场仅保留扩展空间，尚未深入建模。
- Gamma active market 响应缺失稳定 category/tag；当前策略是缺失分类则保留并告警，后续需通过 event/tag 详情或其他来源补全。
- raw API response 已归档，但 market、event、trade、position、holder、orderbook 的 schema/contract 测试还不够细。
- closed positions 当前作为 realized PnL 权威输入；若 Data API 口径变化，需要通过对账报告识别差异。
- Daily equity v1 是 UTC 日期级，不是 tick 级净值。
- `outcome_correct` 只有在 closed position 的 `cur_price` 证据足够强时才设置，否则保持 null。

产品与生产化债务：

- frontend 仍是 Next.js 占位，未开发 dashboard。
- API 目前只有 health、wallet timeline、wallet profile，尚无完整 Dashboard 查询 API。
- 尚未做调度器、任务队列、长期限流策略、监控告警、部署脚本。
- VPS 尚未部署采集节点；部署时仍必须保持只读边界。
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

# 价格与订单簿
python -m backend.scripts.archive_price_data --token-limit 100 --skip-orderbook
python -m backend.scripts.archive_price_data --token-limit 5 --skip-history --orderbook-cycles 3 --orderbook-interval-seconds 2 --depth-limit 5 --websocket --websocket-seconds 10 --websocket-event-limit 10
python -m backend.scripts.archive_price_data --skip-history --skip-orderbook --calculate-clv --clv-limit 1000

# SmartScore 与回测
python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20
python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20 --backtest --strategy-size 10 --validation-days 30

# 24 小时 watchlist 归档形态
python -m backend.scripts.archive_price_data \
  --tokens <comma_separated_watchlist_tokens> \
  --skip-history \
  --orderbook-cycles 2880 \
  --orderbook-interval-seconds 30 \
  --websocket \
  --websocket-seconds 86400 \
  --websocket-event-limit 1000000

# API
uvicorn backend.app.main:app --reload
curl http://127.0.0.1:8000/health
curl 'http://127.0.0.1:8000/wallets/<wallet_address>/timeline?limit=100'
curl 'http://127.0.0.1:8000/wallets/<wallet_address>/profile?market_limit=50'
curl 'http://127.0.0.1:8000/scores/leaderboard?limit=50'

# 关闭本地服务
docker compose -f infra/docker-compose.yml down
```

## 下一步建议

直接进入 Week07：API、Dashboard 与提醒。

建议顺序：

1. 阅读 `../polymarket-wallet-tracker-plan/Week07-API-Dashboard与提醒.md`。
2. 先设计 Dashboard 需要的 API：排行榜、钱包评分拆解、回测摘要、钱包详情跳转。
3. 前端优先展示实际工具界面，不做营销 landing page。
4. 如排行榜高置信钱包为空，先展示 all-ranked 与 failed gate 原因，不要隐藏数据。
5. 继续保持只读边界，不引入真实下单、签名、私钥或交易凭证。
