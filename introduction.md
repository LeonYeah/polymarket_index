# Polymarket Wallet Tracker - 交接说明

更新时间：2026-07-09

下次会话先读本文件，再按目标查看 `../polymarket-wallet-tracker-plan/`。当前建议直接进入 `Week04-PnL引擎与对账.md`。

## 项目目标与边界

目标：建设一个可复现、可审计、可回测的 Polymarket 优质钱包研究系统，用公开只读数据完成市场、钱包、交易、仓位、容量、PnL 和评分分析。

边界：

- 只做公开只读采集、建模、回测和分析。
- 不做真实下单，不保存私钥、签名凭证、交易 cookie、交易 API key。
- USA VPS 只作为公开只读 API 探针/采集节点，不作为真实订单执行节点。
- 未结算浮盈不得计入 realized PnL；`cashPnl/currentValue` 必须与 `realizedPnl` 分离。

## 环境与路径

- 本地仓库：`/home/lee/workspace/search/codes`
- 周计划：`/home/lee/workspace/search/polymarket-wallet-tracker-plan`
- VPS 登录：`ssh usa`
- Python venv：`codes/.venv`
- 最新已提交代码：`fe99c53 完成Week03钱包回填验收`

## 当前架构

```text
codes/
  backend/
    app/
      api/                  FastAPI: health, wallet timeline
      collectors/           Polymarket 只读采集与回填
      core/                 配置、日志、run_id
      db/                   PostgreSQL 连接、schema、repository
      domain/               领域模型草案
    scripts/
      api_probe.py          只读 API 探针
      db_migrate.py         schema 迁移
      ingest_market_data.py 市场/容量/holders 采集
      backfill_wallet_data.py 钱包发现与交易/仓位回填
    tests/                  health、schema、解析、钱包回填测试
  docs/
    api-probe-report.md
    data-dictionary.md
    market-data-ingestion-report.md
    wallet-backfill-report.md
    adr/
    samples/
  frontend/                 Next.js 占位，尚未开发
  infra/                    Docker Compose/Postgres/Redis/backend
```

技术栈：Python、FastAPI、Pydantic、httpx、SQLAlchemy、psycopg、PostgreSQL、Docker Compose。当前未使用 TimescaleDB 特性。

## 已完成能力

基础工程：

- FastAPI 后端骨架、`/health`、配置系统、日志和 run_id 已建立。
- Docker Compose 可启动 PostgreSQL、Redis、backend。
- `.env.example` 不含私密凭证。

只读 API 验证：

- `python -m backend.scripts.api_probe`
- 已验证 Gamma、Data、CLOB HTTP 端点和 CLOB market WebSocket。
- `/trades` 已覆盖并确认必须显式设置 `takerOnly=true/false`。
- 详见 `docs/api-probe-report.md`。

市场数据模型与采集：

- `python -m backend.scripts.db_migrate`
- `python -m backend.scripts.ingest_market_data`
- 已建表：`ingestion_runs`、`events`、`markets`、`market_tokens`、`market_liquidity_snapshots`、`market_holders`、`raw_api_responses`。
- 已实现 Gamma keyset 分页、events/markets/token 映射、OI/live volume/liquidity/holders 入库、raw response 归档。
- `clobTokenIds`、`outcomes` 支持 JSON 字符串；CLOB token id 全部按字符串处理；金额/价格/size 使用 `Decimal`；时间统一 UTC。

市场采集验收：

```text
markets: 500
tokens: 1000
events: 228
token_verifications: 100
token_mapping_failures: 0
holders: 2500+
liquidity_snapshots: 526
重复采集后 markets/tokens/events 未重复膨胀
```

钱包发现与历史行为回填：

- `python -m backend.scripts.backfill_wallet_data`
- 已建表：`wallets`、`wallet_candidates`、`trades`、`wallet_positions_current`、`wallet_positions_closed`、`wallet_activity_daily`、`wallet_backfill_checkpoints`。
- 候选来源：leaderboard DAY/WEEK/MONTH/ALL、Week02 holders、近期 `/trades?takerOnly=false`。
- 交易回填显式记录 `takerOnly=false`；无官方稳定 trade id 时用稳定字段生成 `trade_uid` 去重。
- 当前仓位和已平仓仓位分表保存，`realizedPnl` 与 `cashPnl/currentValue` 分离。
- checkpoint 支持 wallet、endpoint、takerOnly、offset 续跑。
- HTTP 429、5xx、临时网络错误有 retry/backoff；单个钱包失败不会中断整批。
- `GET /wallets/{wallet_address}/timeline` 可查询钱包交易时间线。

Week03 正式验收：

```text
wallet_candidates distinct wallets: 1358
fully backfilled wallets: 320
trade-exhausted wallets: 108
trades: 234957
distinct trade_uid: 234957
wallet_positions_current: 15513
wallet_positions_closed: 14142
wallet_activity_daily: 6557
failed_wallets: 0
```

验证：

```text
pytest -q: 22 passed, 1 warning
ruff check .: passed
timeline API: 200, 返回交易时间线
重复 upsert 同一批 trade: 第二次未新增记录
```

## 关键数据口径

- `/trades` 必须显式设置 `takerOnly`，否则可能漏掉 maker 风格活动。
- 当前先使用 `takerOnly=false` 做主回填口径；maker/taker 双侧归因尚未建模。
- `data/live-volume` 的 `id` 是 Gamma market 数值型 `id`，不是 `condition_id` 或 CLOB token id。
- `data/live-volume` 可能返回不在当前 market 批次里的 condition_id，容量快照表不强制 FK 到 `markets`。
- token 映射按 `clobTokenIds` 与 `outcomes` 顺序建立；长度不一致标记 `mapping_status=failed`。
- 抽样 token 使用 CLOB `markets-by-token/{token_id}` 校验。
- 高活跃钱包仍可能有更深 `/trades` 历史；`status=running` 的 checkpoint 可继续从 offset 续跑。

## 当前未完成与遗留债务

下一阶段核心：

- Week04：PnL 引擎与对账尚未实现。
- 尚未计算 realized PnL、unrealized PnL、费用、结算状态、仓位/交易对账。
- 尚未实现 SmartScore、统计回测、跟单筛选。

数据与模型债务：

- Gamma active market 响应当前缺失稳定 category/tag；已采用“缺失分类则保留并告警”，后续需通过 event/tag 详情或其他来源补全分类。
- raw API response 已归档，但关键响应 schema/contract 测试还不够细，尤其是 market、event、trade、position、holder、orderbook。
- maker/taker 双侧钱包归因尚未处理。
- 高活跃钱包的 `/trades` 深层历史可继续从 checkpoint 续跑。

价格与订单簿：

- 已验证 CLOB book/prices-history/WebSocket 可用。
- 尚未建立价格历史、订单簿快照表和定时采集任务。

API/前端/生产化：

- API 目前只有 health 与 wallet timeline；尚未做完整 Dashboard 查询 API。
- frontend 仍是 Next.js 占位，尚未开发 dashboard。
- 尚未做调度器、任务队列、长期限流策略、监控告警、部署脚本。
- VPS 目前没有需要提交的代码；后续部署采集节点仍必须保持只读边界。

## 常用命令

本地验证：

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate
pytest -q
ruff check .
```

启动数据库与迁移：

```bash
docker compose -f infra/docker-compose.yml up -d postgres
python -m backend.scripts.db_migrate
```

市场采集 smoke：

```bash
python -m backend.scripts.ingest_market_data --max-markets 5 --page-limit 5 --holders-market-limit 2 --holders-limit 3
```

钱包回填 smoke：

```bash
python -m backend.scripts.backfill_wallet_data --candidate-limit 5 --leaderboard-limit 3 --holder-candidate-limit 3 --active-trader-limit 3 --backfill-wallet-limit 1 --page-limit 2 --max-trade-pages 1
```

启动 API：

```bash
uvicorn backend.app.main:app --reload
curl http://127.0.0.1:8000/health
curl 'http://127.0.0.1:8000/wallets/<wallet_address>/timeline?limit=100'
```

关闭本地容器：

```bash
docker compose -f infra/docker-compose.yml down
```

## 建议下一步

进入 Week04：PnL 引擎与对账。

建议顺序：

1. 阅读 `../polymarket-wallet-tracker-plan/Week04-PnL引擎与对账.md`。
2. 基于 `trades`、`wallet_positions_current`、`wallet_positions_closed` 设计 PnL schema 与 repository。
3. 先实现 realized PnL 与 closed positions 对账；不得把 `cashPnl/currentValue` 混入 realized PnL。
4. 再实现 unrealized PnL、当前仓位估值和异常差异报告。
5. 只读边界不变，不做真实下单。

下次会话可直接提示：

```text
请先阅读 codes/introduction.md 和 polymarket-wallet-tracker-plan/Week04-PnL引擎与对账.md。
当前 Week01/Week02/Week03 核心能力已完成：只读 API 探针、市场/容量/holders 采集、1358 个候选钱包、320 个完整回填钱包、234957 条唯一 trades、钱包 timeline API。
请继续推进 Week04：PnL 引擎与对账。保持只读边界，不要加入私钥、签名、真实下单或交易凭证。
```
