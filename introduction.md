# Polymarket Wallet Tracker - 当前交接说明

更新时间：2026-07-09
本文件是下次 Codex 会话的入口。先读本文件，再按需要查看 `docs/` 和 `../polymarket-wallet-tracker-plan/Week02-数据模型与市场数据采集.md`。

## 项目定位

目标是建设一个可复现、可审计、可回测的 Polymarket 优质钱包研究系统。当前阶段只做公开数据采集、字段验证、数据建模和后续回测准备；不做真实下单，不保存私钥、签名凭证、交易 cookie 或交易 API key。

核心边界：

- 本机/WSL：代码、文档、开发、重计算、回测、密钥和未来人工确认执行。
- USA VPS：只读 API 探针和后续公开数据采集节点。
- USA VPS 不作为真实订单执行节点。

## 当前路径与环境

- 本地代码目录：`/home/lee/workspace/search/codes`
- 远端同路径目录：`/home/lee/workspace/search/codes`
- VPS SSH：`ssh usa`，端口 `609`
- 本机运行环境：WSL
- Docker：Windows Docker Desktop，已开启 WSL Integration
- Python 虚拟环境：`codes/.venv`

## 当前架构

```text
codes/
  backend/                  FastAPI 后端、配置、API 探针、领域模型草案
  frontend/                 Next.js dashboard 空壳
  infra/                    本地 Docker Compose 与 backend Dockerfile
  docs/                     ADR、字段字典、API 验证报告、样例摘要
  pyproject.toml            Python 依赖与测试/ruff 配置
  .env.example              本地配置模板，不含密钥
```

技术栈现状：

- Backend：Python 3.12、FastAPI、Pydantic、httpx、structlog
- Probe：httpx + websockets，只读公开 API
- Local infra：Docker Compose 启动 PostgreSQL、Redis、backend
- Frontend：Next.js + TypeScript 占位，尚未开发页面

## Week01 已完成

1. 后端骨架
   - FastAPI app 已建立。
   - `/health` 已实现并验证正常。
   - 配置系统支持 `DATABASE_URL`、`REDIS_URL`、Gamma/Data/CLOB/WebSocket base URL。

2. API 探针
   - 探针脚本：`backend/scripts/api_probe.py`
   - 每次运行生成 `run_id`。
   - 样例输出到 `docs/samples/` 或指定目录。
   - 不访问下单接口，不使用任何私密凭证。

3. 接口验证
   - Gamma：`markets/keyset`、`events/keyset`
   - Data：`leaderboard`、`holders`、`positions`、`closed-positions`、`trades`、`oi`、`live-volume`
   - CLOB：`book`、`prices-history`、`markets/{condition_id}`
   - WebSocket：`/ws/market` 已收到初始 orderbook snapshot
   - `/trades` 已覆盖 `takerOnly=true` 和 `takerOnly=false`

4. 文档
   - 字段字典：`docs/data-dictionary.md`
   - API 验证报告：`docs/api-probe-report.md`
   - 技术决策：`docs/adr/0001-tech-stack.md`
   - VPS API 摘要样例：`docs/samples/week01-vps-*.json`

5. 本地验证
   - `pytest -q` 通过。
   - `ruff check .` 通过。
   - 本地 venv 运行 `/health` 通过。
   - 真实只读 API 探针通过：normal HTTP 用例全部成功，invalid 用例按预期返回 4xx，WebSocket 成功。
   - Docker Compose 已通过：PostgreSQL/Redis healthy，backend `/health` 返回正常。

6. VPS 与 SSH
   - VPS 已创建 `/home/lee/workspace/search/codes`。
   - `ssh usa` 已从端口 22 切到 609。
   - VPS 当前只做只读 API 探针/采集，不用 Docker。

## 已确认的数据口径与风险

- `/trades` 必须显式设置 `takerOnly`，否则可能漏掉 maker 风格钱包。
- `data/live-volume` 的 `id` 是 Gamma market 的数值型 `id`，不是 `condition_id`，也不是 CLOB token id。
- CLOB token id 必须按字符串处理，不能按整数处理。
- 金额、价格、size 使用 Decimal 或定点数，不用 binary float。
- 时间统一归一化为 UTC；CLOB WebSocket 中已观察到毫秒字符串时间戳。
- 未结算浮盈不得计入 realized PnL。
- VPS 所在 US 区域此前订单接口测试返回 trading restricted；不要在 VPS 上实现真实下单。

## 常用命令

本地 Python：

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate
pytest -q
ruff check .
uvicorn backend.app.main:app --reload
curl http://127.0.0.1:8000/health
```

API 探针：

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate
python -m backend.scripts.api_probe --output-dir /tmp/polymarket-probe-samples
```

Docker Compose：

```bash
cd /home/lee/workspace/search/codes
docker compose -f infra/docker-compose.yml up -d --build
curl http://127.0.0.1:8000/health
docker compose -f infra/docker-compose.yml down
```

Docker 说明：backend 默认基础镜像是 `mirror.gcr.io/library/python:3.12-slim`，用于规避 Docker Hub 拉取不稳定。需要改回 Docker Hub 时可覆盖 `PYTHON_IMAGE=python:3.12-slim`。

VPS：

```bash
ssh usa
```

## Week02 当前进展

已完成第一条可运行纵切：

1. PostgreSQL schema v1：
   - `ingestion_runs`
   - `events`
   - `markets`
   - `market_tokens`
   - `market_liquidity_snapshots`
   - `market_holders`
   - `raw_api_responses`
2. 等价迁移机制：
   - `python -m backend.scripts.db_migrate`
3. 市场数据采集 worker：
   - `python -m backend.scripts.ingest_market_data`
   - 支持 Gamma markets/events、token 映射、OI、live volume、holders、raw response 入库。
4. 本地小批真实采集已验证：
   - 连续运行 2 次后，`markets=5`、`market_tokens=10` 未重复膨胀。
   - run-scoped snapshots、holders、raw responses 按批次保留。
   - token 映射失败数为 0。
5. 测试：
   - `pytest -q`：10 passed。
   - `ruff check .`：通过。

验收报告见 `docs/market-data-ingestion-report.md`。

## 下一步：继续 Week02

优先事项：

1. 针对 Gamma keyset cursor 做更大规模分页验证。
2. 将采集规模提升到至少 500 个市场或当前目标市场全集。
3. 增加 token 到 CLOB `markets-by-token/{token_id}` 或可用等价端点的抽样校验。
4. 为 raw API response 增加更细的字段稳定性测试。
5. 补全目标分类 Politics、Finance、Tech 的筛选策略。
6. 暂不做 PnL、评分、真实下单或复杂 dashboard。

下次会话建议提示：

```text
请先阅读 codes/introduction.md 和 polymarket-wallet-tracker-plan/Week02-数据模型与市场数据采集.md。
基于当前 Week01 已完成的 FastAPI、API 探针、Docker Compose 和字段字典，继续推进 Week02。
保持两端架构：VPS 只做公开只读采集，本机保留代码、文档、重计算和未来执行边界。
不要把私钥、签名、真实订单执行放到 VPS 或仓库。
```
