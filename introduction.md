# Polymarket Wallet Tracker — 项目交接

更新时间：2026-07-15

## 新会话快速入口

1. 阅读本文件与 `docs/vps-sampling-runbook.md`。
2. 执行 `git status --short --branch`，保留已有修改。
3. 检查 VPS 服务与采样健康：

   ```bash
   ssh usa 'systemctl is-active postgresql polymarket-api polymarket-sampler \
     polymarket-maintenance.timer polymarket-health.timer polymarket-backup.timer'
   ssh usa 'curl -fsS http://127.0.0.1:8000/paper/health'
   ssh usa 'systemctl --failed --no-pager'
   ```

4. 当前主线是完成连续采样验收并积累可用 CLV、followability 和纸面成交样本，不是真实下单。
5. 连续验收起点为 `2026-07-15 10:15:13 UTC`，最早在 `2026-07-22 10:15:13 UTC` 后评估。

## 目标与安全边界

本项目使用 Polymarket 公开数据，对钱包进行可复现、可审计、可解释的研究，覆盖数据采集、PnL、订单簿、CLV、SmartScore、回测、告警和纸面跟单。

- 只调用公开只读接口，不保存私钥、签名凭证、交易 cookie 或真实下单 API key。
- VPS 只负责采集、分析、API 和纸面模拟，不签名订单、不调用真实下单端点、不发送链上交易。
- `realized_pnl` 仅表示已结算或已平仓收益；未实现浮盈、`cashPnl`、`currentValue` 分开记录。
- SmartScore、回测、告警和 paper order 都是研究证据，不是收益承诺或交易指令。
- 在至少 2–4 周纸面结果稳定且风险机制完成前，不进入真实执行阶段。

## 当前架构

```text
Polymarket Gamma / Data / CLOB 公共 API
                    │
                    ▼
USA VPS /opt/polymarket-wallet-tracker
  ├─ polymarket-sampler.service      每分钟连续采样与 paper cycle
  ├─ polymarket-api.service          FastAPI，仅 127.0.0.1:8000
  ├─ polymarket-maintenance.timer    每 6 小时维护分析数据
  ├─ polymarket-health.timer         每 5 分钟检查 freshness
  ├─ polymarket-backup.timer         每日数据库备份，保留 14 天
  └─ PostgreSQL 16                   仅本机 socket/loopback
                    │
                    │ SSH 隧道：本机 8001 → VPS 8000
                    ▼
WSL Next.js Dashboard：127.0.0.1:3000
```

连续采样链路：

1. 从候选钱包中选 Top 25 作为只读研究池，与严格 paper 池取并集。
2. 从 Data API offset 0 拉取这些钱包的最新交易，避免历史 checkpoint 完成后漏掉新交易。
3. 根据钱包近期交易、watchlist 和 pending signal 选择最多 30 个 token，采集 CLOB 订单簿与 followability。
4. Signal/Paper Engine 独立重放严格评分、置信度和风险门槛；研究池身份不授予模拟成交资格。
5. maintenance 先直接刷新全部 open paper position 对应市场，再进行常规市场采集，并按“候选发现/回填 → 成熟 CLV → PnL/市场 resolution → SmartScore”继续运行；paper cycle 据此完成 settlement，各阶段失败隔离。

### 代码结构

```text
backend/app/collectors/  市场、钱包、交易、价格、订单簿、WebSocket 采集
backend/app/analytics/   PnL、特征、SmartScore、回测、paper trading
backend/app/db/          schema 与各领域 repository
backend/app/api/         wallet、market、score、alert、watchlist、paper API
backend/scripts/         迁移、采集、分析、维护与健康检查入口
backend/tests/           数据合同、分析、schema、API 与持续采样测试
frontend/                Next.js Dashboard
deploy/                  systemd、健康检查与 PostgreSQL 备份
docs/                    数据字典、设计报告、验收报告和运行手册
infra/                   WSL 本地开发用 Docker Compose
```

技术栈：Python、FastAPI、Pydantic、httpx、SQLAlchemy、psycopg、PostgreSQL、Next.js、TypeScript。Redis 只有本地开发配置，业务尚未使用。

## 环境、数据库与备份

| 环境 | 用途 | 数据库实体数据 | 当前规模 | 备份 |
|---|---|---|---|---|
| VPS `ssh usa` | 持续运行的主数据源 | `/var/lib/postgresql/16/main` | `polymarket` 约 6.24 GB | `/var/backups/polymarket/polymarket-*.dump`，custom format，每日、保留 14 天 |
| WSL Docker | 独立开发副本 | 容器内 `/var/lib/postgresql/data`；volume `infra_postgres_data` | `polymarket` 约 757 MB；volume 约 1.0 GB | 当前没有项目数据库 dump |
| WSL 原生 PostgreSQL | 未使用 | 原生服务当前 inactive | 无运行中实例 | 未发现 `.dump/.sql/.backup` |

- WSL Docker volume 由 Docker Desktop 管理。`docker inspect` 显示源路径 `/var/lib/docker/volumes/infra_postgres_data/_data`，但该路径不一定能从当前 WSL mount namespace 直接访问；应使用 `docker exec`、`docker compose` 或 `docker cp` 操作。
- WSL 与 VPS 数据库不会自动同步。本地 Dashboard 默认应通过 SSH 隧道读取 VPS API，不能把本地容器数据当作生产实时数据。
- VPS 数据库和 API 都未暴露公网；数据库 `polymarket` 与角色 `polymarket` 使用本机 peer 认证。

## 全项目已完成能力

### 数据平台

- PostgreSQL schema、结构化日志、`run_id`、ingestion run、raw response 和 checkpoint 可追踪。
- 金额、价格和 size 使用 `Decimal`；token id 保持字符串；时间统一为 UTC。
- 已采集 events、markets、token/outcome 映射、OI、volume、liquidity、holders、trades、current/closed positions。
- 候选钱包来自 leaderboard、holders 和 active traders；支持幂等 upsert、稳定 `trade_uid` 去重、失败隔离和受限历史回填。
- 已归档价格历史、有限档订单簿、top bid/ask、midpoint、spread、depth、followability 与 WebSocket 事件。
- 数据采样池和允许纸面成交的钱包池已拆分；Top 25 候选即使未达到 60 分也持续采集，但不会绕过 paper gates。

### 分析与评分

- PnL Engine 已生成 wallet-market 结果、日级 equity 和 reconciliation checks，区分 realized/unrealized PnL、current value、ROI、profit factor、drawdown 与集中度。
- 已实现 signed CLV（30s、2m、10m、1h、24h）、保守滑点和 `market_liquidity_score`。
- maintenance 每 6 小时为研究池与严格池补算最多 1000 条未计算或新近成熟的 CLV，再刷新 PnL 与 SmartScore。
- Feature Engine、SmartScore v2、hard gates、惩罚、confidence 和组件拆解均版本化落库。
- 回测可比较 `top_score`、`top_pnl`、`random_active`，关键小样本和集中度行为已有测试。

### API、Dashboard 与告警

- FastAPI 提供钱包榜、钱包详情、钱包市场、市场详情、smart-flow、评分、回测、告警、watchlist 和 paper API。
- API 统一分页与错误结构；金额声明 USDC；时间输出 ISO 8601 UTC。
- Next.js 已有首页、钱包详情、市场详情、告警操作、watchlist 和 `/paper` 页面。
- watchlist 修改有操作者、时间和内容审计；告警支持 `open → ack → resolved`。
- 已实现高分钱包建仓、多钱包同向、临近结束大仓、流动性恶化、采集延迟五类规则。
- 已完成本地性能基线：被测核心接口 p95 均低于 500 ms。

### 纸面交易与生产运行

- 已落地 signals、paper orders/events、positions 和 PnL 表及 API 展示。
- 支持多钱包信号加权与合并、订单簿逐档模拟、FOK/FAK/GTC、部分成交、GTC 过期、结算和三段延迟。
- 单 strategy/token 的累计 open cost basis 默认上限为 100 USDC，由 `PAPER_MAXIMUM_TOKEN_NOTIONAL` 配置；达到上限时拒单，剩余额度不足时按额度缩小模拟成交。
- active watchlist 钱包保留 score 60 豁免，但不能绕过 confidence、流动性、价差、数据新鲜度、预期边际等风险门槛。
- 市场采集会优先直连 Gamma 刷新全部 open paper position 对应市场；resolution 解析 outcome 与最终价格后，paper cycle 将订单和仓位推进为 settled。
- PnL 区分 gross、fee、slippage、net，以及“方向正确但费用后亏损”。
- VPS 已完成原生 PostgreSQL、systemd 自恢复、freshness 健康检查、六小时维护与每日备份部署。
- 当前验证基线：后端 `86 passed`、Ruff 通过、Next.js production build 通过；只有既存 TestClient/httpx 弃用 warning。
- root 环境已安装 `fnm 1.39.0`，项目用 `.node-version` 固定 Node `22.23.1`，不再依赖 `.vscode-remote-containers` 内的 Node。

## 当前运行状态

- VPS 服务与 timers 均 active，无 failed systemd unit；健康接口通常为 `healthy`。采样周期执行中会短暂显示 `degraded`，周期成功结束后恢复，需结合 job status 判断。
- sampler 每轮取 Top 25 研究钱包与严格 paper 钱包的并集；每轮最多归档 30 个相关 token 的订单簿。
- 最近一次 maintenance 成功刷新 1000 条 CLV；数据库现有 1200 条 CLV 行，其中 462 条至少有一个可用时间窗。
- 最新评分覆盖 150 个钱包，最高分 `54.6848`；达到 `score >= 60` 的钱包为 0，高置信可跟单钱包为 0。
- 2026-07-15 已优先刷新并结算 France 2026 World Cup `No` 仓位：1 个 position、89 笔 paper order 均为 settled，结算价 1，汇总 net PnL `1798.585324` USDC；当前 open position 与未结算模拟订单均为 0。该样本高度集中且费用模型仍为占位，不能据此评价策略稳定性。
- VPS 已部署 schema `2026_07_15_paper_risk_and_resolution_v1`；`/paper/health` 为 healthy，采样进程已加载 100 USDC 单 token 上限。

## 未完成事项与技术债务

### P0：运行验收与可观测性

- 完成连续 7 天验收：核对周期缺口、失败次数、freshness、订单簿成功率、服务重启、磁盘增长和备份连续性，并更新正式验收报告。
- 至少积累 2–4 周且覆盖多个独立市场的纸面结果；当前只有 1 个已结算仓位、89 笔同源订单，仍无法可靠评价 net ROI、win rate、max drawdown 和策略稳定性。
- 告警规则尚未由 VPS timer 定时生成，也没有邮件、Webhook 等外部通知和升级机制。
- 数据库备份尚未执行完整恢复演练；需要在隔离环境验证 dump 可恢复、schema 完整和服务可启动。
- VPS 磁盘仅 38 GB，数据库增长快；需建立容量阈值、增长率监控和归档/清理策略。

### P1：数据质量与模型

- CLV 与 followability 覆盖仍低；需扩大有效 token 覆盖并提高长期订单簿/WebSocket 连续性。
- PnL 的 `estimated_slippage` 尚未用历史订单簿回写；费用模型仍是版本化占位，未按市场和 maker/taker 角色校准。
- category/tag 来源不完整；category expertise 仍使用 confidence 代理，尚无钱包 × category 独立历史特征。
- 回测是近似时间切分；严格历史重放需要按 cutoff 重建当时特征、仓位、评分和订单簿。
- SmartScore 的 network signal 仍为中性占位；资金来源、协同交易、钱包聚类和关联风险尚未实现。
- maker/taker 双侧归因、负风险、组合市场、多 outcome 市场和复杂结算仍需深入建模。
- `outcome_correct` 只在证据充分时设置；daily equity 仍按 UTC 日级；smart-flow 尚无独立全局 freshness SLA。
- 部分 market/event/trade/position/holder/orderbook schema contract 与异常数据测试仍不足。

### P2：产品与工程

- Dashboard 仅适合本地研究，没有认证、权限隔离、浏览器 E2E 或视觉回归。
- 尚无 Prometheus/集中指标、SLO 仪表盘、自动通知、容量报警和完整故障演练。
- Redis、缓存和限流尚未接入；数据继续增长后需重新压测 API p95 和慢查询。
- 本地与 VPS 数据库无自动同步；环境变量或 SSH 隧道错误时前端可能读取空的本地数据。
- 真实下单、私钥管理、人工确认、权限隔离、止损/限额和执行风控均未实现，当前也不应启动开发。

## 关键数据口径

- `data/live-volume.id` 是 Gamma market 数值 id，不是 `condition_id` 或 CLOB token id。
- token 必须按 `clobTokenIds` 与 `outcomes` 的顺序映射，不能按文本猜测。
- `prices-history` 不是历史订单簿；精确成交与滑点只能使用对应时点的 book、spread、depth 和 freshness。
- 未归档 token 的 followability 必须保守处理；页面必须展示 confidence、failed gates 和原因。
- `paper_orders` 是数据库中的反事实模拟记录；即使状态为 `would_fill`，也没有向 Polymarket 发单。

## 常用操作

查看 VPS 数据库与存储：

```bash
ssh usa 'sudo -u polymarket psql -d polymarket'
ssh usa 'sudo -u postgres psql -Atqc "show data_directory"'
ssh usa 'du -sh /var/lib/postgresql/16/main /var/backups/polymarket; df -h /'
```

查看 WSL 开发数据库：

```bash
docker exec -it infra-postgres-1 psql -U polymarket -d polymarket
docker exec infra-postgres-1 du -sh /var/lib/postgresql/data
docker volume inspect infra_postgres_data
```

本地查看 VPS Dashboard：

```bash
# 终端一
ssh -N -L 8001:127.0.0.1:8000 usa

# 终端二（root）
cd /home/lee/workspace/search/codes
eval "$(fnm env --shell bash)"
fnm use
cd frontend
API_BASE_URL=http://127.0.0.1:8001 \
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 \
npm run dev -- --hostname 127.0.0.1 --port 3000
```

验证代码：

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate
pytest -q
ruff check .

cd frontend
npm run build
```

## 关键文档

- `docs/vps-sampling-runbook.md`：VPS 服务、采样语义、备份、隧道和验收窗口。
- `docs/data-dictionary.md`：字段定义与数据口径。
- `docs/smart-score-v2-report.md`：候选发现、评分与 hard gates。
- `docs/pnl-engine-report.md`、`docs/price-archive-report.md`：PnL、订单簿、CLV 与限制。
- `docs/week07-acceptance-report.md`、`docs/week08-acceptance-report.md`：API/Dashboard 与纸面系统的历史验收记录；其中旧运行时间点以本文件和 runbook 为准。

## 下一步推荐顺序

1. 每次会话先查 health、最近 sampler/maintenance 日志、failed units、磁盘和备份。
2. 到 7 天窗口后生成连续采样验收报告；窗口未满则继续采集，不提前宣称通过。
3. 分析拒单分布及 confidence、CLV、followability 缺口，优先获得可信的纸面成交样本。
4. 部署告警定时生成与外部通知，完成数据库恢复演练和磁盘容量报警。
5. 在纸面证据稳定前保持严格门槛，不开发或接入真实下单。
