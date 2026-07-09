# Polymarket Wallet Tracker - 交接说明

更新时间：2026-07-09

本文件是下次 Codex 会话的入口。先读本文件，再按当前目标查看：

- 周计划：`../polymarket-wallet-tracker-plan/`
- API/字段报告：`docs/`
- 当前验收报告：`docs/market-data-ingestion-report.md`、`docs/wallet-backfill-report.md`

## 项目目标与边界

目标：建设一个可复现、可审计、可回测的 Polymarket 优质钱包研究系统，用公开数据完成市场、钱包、交易、仓位、容量和后续 PnL/评分分析。

当前边界：

- 只做公开只读数据采集、字段验证、数据建模、回测准备。
- 不做真实下单。
- 不保存私钥、签名凭证、交易 cookie、交易 API key。
- USA VPS 只作为公开只读 API 探针/采集节点，不作为真实订单执行节点。

## 环境与路径

- 本地代码目录：`/home/lee/workspace/search/codes`
- 远端同路径目录：`/home/lee/workspace/search/codes`
- VPS SSH：`ssh usa`
- 本机环境：WSL + Windows Docker Desktop WSL Integration
- Python venv：`codes/.venv`
- Git 仓库：`codes/`

当前提交：

```text
当前最新提交：实现钱包发现与回填闭环（本文件所在提交）
b001ba5 更新Week02验收交接说明
7e9bd7c 完善市场分页采集与token校验
eb2f49c 新增市场数据模型与采集管道
6ad979c 初始化只读Polymarket钱包追踪项目
```

## 当前架构

```text
codes/
  backend/
    app/
      api/                  FastAPI API，目前只有 health
      collectors/           Polymarket 只读采集逻辑
      core/                 配置、日志、run_id
      db/                   数据库连接、schema 迁移、repository
      domain/               领域模型草案
    scripts/
      api_probe.py          只读 API 探针
      db_migrate.py         PostgreSQL schema 迁移
      ingest_market_data.py 市场数据采集入口
      backfill_wallet_data.py 钱包发现与回填入口
    tests/                  health、schema、数据解析测试、钱包回填解析测试
  docs/
    adr/                    技术决策
    samples/                脱敏样例摘要
    api-probe-report.md
    data-dictionary.md
    market-data-ingestion-report.md
  frontend/                 Next.js 占位，尚未开发 dashboard
  infra/
    docker-compose.yml      本地 Postgres、Redis、backend
    Dockerfile.backend
  pyproject.toml
  .env.example
```

技术栈：

- Backend：Python、FastAPI、Pydantic、httpx、SQLAlchemy、psycopg、structlog
- DB：PostgreSQL；当前未使用 TimescaleDB 特性
- Infra：Docker Compose 本地开发
- Frontend：Next.js + TypeScript 占位

## 已完成能力

基础工程：

- FastAPI 后端骨架已建立。
- `/health` 可用。
- 配置系统支持数据库、Redis、Gamma/Data/CLOB/WebSocket base URL。
- Docker Compose 可启动本地 PostgreSQL、Redis、backend。
- `.env.example` 不含私密凭证。

只读 API 探针：

- `python -m backend.scripts.api_probe`
- 每次运行生成 `run_id`。
- 已验证 Gamma、Data、CLOB HTTP 端点和 CLOB market WebSocket。
- `/trades` 已显式覆盖 `takerOnly=true/false`。
- 样例和报告见 `docs/api-probe-report.md`、`docs/samples/`。

数据模型与迁移：

- `python -m backend.scripts.db_migrate`
- PostgreSQL schema v1 已建立：
  - `ingestion_runs`
  - `events`
  - `markets`
  - `market_tokens`
  - `market_liquidity_snapshots`
  - `market_holders`
  - `raw_api_responses`
- 所有核心表保留 `source`、`ingestion_run_id`、`created_at`、`updated_at`。
- 快照表保留 `snapshot_at` 和原始/标准化数值。

市场数据采集：

- `python -m backend.scripts.ingest_market_data`
- 使用 Gamma keyset 分页，正确使用 `next_cursor -> after_cursor`。
- 采集并入库 markets、embedded events、token 映射、OI、live volume、liquidity、holders。
- raw API response 记录请求参数、状态码、耗时、row count、hash、JSON body。
- `clobTokenIds`、`outcomes` 支持 Gamma 返回 JSON 字符串的情况。
- CLOB token id 全部按字符串处理。
- 金额、价格、size 使用 `Decimal`。
- 时间统一归一化 UTC，支持毫秒时间戳。

钱包发现与回填：

- `python -m backend.scripts.backfill_wallet_data`
- Week03 schema 已建立：
  - `wallets`
  - `wallet_candidates`
  - `trades`
  - `wallet_positions_current`
  - `wallet_positions_closed`
  - `wallet_activity_daily`
  - `wallet_backfill_checkpoints`
- 候选来源覆盖 leaderboard DAY/WEEK/MONTH/ALL、Week02 holders、近期 `/trades?takerOnly=false`。
- `/trades` 回填显式记录 `takerOnly=false`，用稳定字段生成 `trade_uid` 去重。
- 当前仓位与已平仓仓位分表保存，`realizedPnl` 与 `cashPnl/currentValue` 分离。
- checkpoint 使用 wallet、endpoint、takerOnly、offset 记录续跑状态。

已完成真实验收：

```text
markets: 500
tokens: 1000
events: 228
token_verifications: 100
token_mapping_failures: 0
holders: 2500
liquidity_snapshots: 526
```

重复采集主数据幂等：

```text
events: 228
markets: 500
market_tokens: 1000
mapping_status.verified: 100
mapping_status.mapped: 900
latest_error: None
```

验证命令：

```text
pytest -q: 20 passed, 1 warning
ruff check .: passed
```

Week03 smoke 验收：

```text
wallets: 9
wallet_candidates: 18
trades: 2
wallet_positions_current: 2
wallet_positions_closed: 2
wallet_backfill_checkpoints: 3
```

## 已确认的数据口径

- `/trades` 必须显式设置 `takerOnly`，否则可能漏掉 maker 风格钱包。
- `data/live-volume` 的 `id` 是 Gamma market 数值型 `id`，不是 `condition_id` 或 CLOB token id。
- `data/live-volume` 可能返回不在当前 market 批次里的 condition_id，容量快照表不强制 FK 到 `markets`。
- token 映射按 `clobTokenIds` 与 `outcomes` 顺序建立；长度不一致标记 `mapping_status=failed`。
- 抽样 token 使用 CLOB `markets-by-token/{token_id}` 校验。
- 未结算浮盈不得计入 realized PnL。
- VPS 所在 US 区域此前订单接口测试返回 trading restricted；不要在 VPS 上实现真实下单。

## 当前未完成与遗留债务

分类补全：

- Gamma active market 响应当前缺失 `category/tag` 字段。
- 当前策略：有分类则过滤；缺失分类则保留并记录 `gamma_market_category_missing_retained_for_ingestion`，避免误删市场。
- 后续需要通过 event/tag 详情端点或其他稳定来源补全 Politics、Finance、Tech 等分类。

字段稳定性：

- raw API response 已归档，但字段稳定性测试还不够细。
- 后续应对关键响应建立 schema/contract 测试，尤其是 market、event、trade、position、holder、orderbook。

钱包与交易：

- Week03 已完成最小闭环和 smoke test，但尚未跑满计划验收规模。
- 尚需分批运行到不少于 500 个 distinct 候选钱包，并至少回填 100 个钱包。
- 尚未处理 maker/taker 双侧钱包归因；当前保留 `takerOnly=false` 口径避免默认漏数。
- 尚未实现钱包交易时间线 API。

PnL 与评分：

- 尚未实现 realized PnL、unrealized PnL、费用、结算状态、对账。
- 尚未实现 SmartScore、统计回测、跟单筛选。

价格与订单簿：

- 已验证 CLOB book/prices-history/WebSocket 可用，但尚未做订单簿/价格历史归档表和定时采集。

前端与提醒：

- frontend 只是 Next.js 占位。
- 尚未实现 dashboard、API 查询接口、提醒系统。

生产化：

- 尚未做调度器、重试队列、限流策略、监控告警、长期运行部署。
- VPS 目录目前没有需要提交的代码；如后续部署采集节点，应继续保持只读边界。

## 常用命令

本地验证：

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate
pytest -q
ruff check .
```

启动后端：

```bash
uvicorn backend.app.main:app --reload
curl http://127.0.0.1:8000/health
```

API 探针：

```bash
python -m backend.scripts.api_probe --output-dir /tmp/polymarket-probe-samples
```

数据库迁移与采集：

```bash
docker compose -f infra/docker-compose.yml up -d postgres
python -m backend.scripts.db_migrate
python -m backend.scripts.ingest_market_data --max-markets 500 --page-limit 100 --holders-market-limit 25 --holders-limit 50 --token-verification-limit 100
docker compose -f infra/docker-compose.yml down
```

钱包发现与回填 smoke test：

```bash
python -m backend.scripts.db_migrate
python -m backend.scripts.backfill_wallet_data --candidate-limit 5 --leaderboard-limit 3 --holder-candidate-limit 3 --active-trader-limit 3 --backfill-wallet-limit 1 --page-limit 2 --max-trade-pages 1
```

钱包发现与回填默认目标：

```bash
python -m backend.scripts.backfill_wallet_data
```

小规模 smoke test：

```bash
python -m backend.scripts.ingest_market_data --max-markets 5 --page-limit 5 --holders-market-limit 2 --holders-limit 3
```

Docker Compose 全量本地服务：

```bash
docker compose -f infra/docker-compose.yml up -d --build
curl http://127.0.0.1:8000/health
docker compose -f infra/docker-compose.yml down
```

VPS：

```bash
ssh usa
```

## 建议下一步

继续 Week03：分批放大钱包发现与历史行为回填。

建议顺序：

1. 读 `../polymarket-wallet-tracker-plan/Week03-钱包发现与历史行为回填.md`。
2. 在已有 Week03 schema 和 `backfill_wallet_data` worker 基础上做分批回填。
3. 先跑 candidate-only 或小批 10/25/50 钱包，观察限流和失败率。
4. 达到不少于 500 个候选钱包和 100 个完成回填钱包后，补充正式验收记录。
5. 保留 `takerOnly=false` 采集，避免漏掉 maker 风格钱包。
6. 暂不做 PnL、评分、真实下单或复杂 dashboard。

下次会话提示可直接使用：

```text
请先阅读 codes/introduction.md 和 polymarket-wallet-tracker-plan/Week03-钱包发现与历史行为回填.md。
当前 Week01/Week02 核心能力已完成；Week03 已有 wallets/trades/positions schema、回填 worker 和 smoke test。
请继续推进 Week03 的分批放大验收：500 个候选钱包、100 个钱包完成 trades/positions/closed_positions 回填。
保持只读边界，不要把私钥、签名、真实订单执行放到 VPS 或仓库。
```
