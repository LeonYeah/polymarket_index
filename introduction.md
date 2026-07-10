# Polymarket Wallet Tracker - 项目交接

更新时间：2026-07-10

## 下次会话入口

1. 先读本文件，再读 `../polymarket-wallet-tracker-plan/Week08-纸面跟单系统.md`。
2. 当前 Week01-Week08 代码闭环已完成；Week08 的 7 天连续运行仍在等待长期采样验收。
3. 纸面系统只生成信号、模拟订单和模拟收益，不连接真实下单，不引入私钥或交易凭证。
4. Week07 功能基线：`337abd9 完成Week07验收与API契约完善`。开始工作前先执行 `git status`，不要覆盖用户已有修改。

## 项目目标与边界

目标：基于 Polymarket 公开数据，建设可复现、可审计、可解释、可回测的钱包研究系统，覆盖市场采集、钱包发现、PnL、CLV、SmartScore、告警和纸面跟单。

硬边界：

- 只使用公开只读接口；不保存私钥、签名凭证、交易 cookie 或交易 API key。
- 当前不做真实下单。USA VPS 仅用于公开 API 探针或采集，不作为执行节点。
- `realized_pnl` 只包含已结算/已平仓收益；`cashPnl`、`currentValue` 和未结算浮盈必须单独展示。
- SmartScore、告警和回测都是研究证据，不是收益承诺或交易指令。

## 当前状态

- 本地仓库：`/home/lee/workspace/search/codes`
- 周计划：`/home/lee/workspace/search/polymarket-wallet-tracker-plan`
- Python 环境：`/home/lee/workspace/search/codes/.venv`
- VPS：`ssh usa`；VPS 的 `codes` 仍为空 Git 仓库，无待提交代码。
- 数据库 schema 已推进到 Week08；PostgreSQL 由 `infra/docker-compose.yml` 管理。
- 自动化验证：`75 passed`、`ruff check .` 通过、Next.js production build 通过。
- Week07 验收快照：1,358 个钱包、500 个市场、16,181 条钱包市场结果、150 个最新评分钱包；Dashboard 实际返回 100 个钱包和 100 个市场。
- 本地 API p95：钱包榜 21.153ms、市场列表 20.239ms、告警列表 17.776ms，均低于 500ms。
- 告警真实验收：生成 5 条采集延迟告警；完成一条 `open -> ack -> resolved` 流转；钱包和市场 watchlist 各写入一条并产生 2 条审计记录。
- Week08 真实 smoke：1 个成功周期、100 个 signal、100 个模拟订单；当前样本全部因 confidence 0.2008 低于 0.35 被拒绝，未虚构成交和收益。
- 当前高置信钱包为 0。主要原因是订单簿、CLV、followability 历史覆盖不足；系统会展示低置信状态和失败门槛，不会把低质量样本包装成高置信结果。

## 当前架构

```text
codes/
  backend/
    app/
      collectors/   Gamma、Data、CLOB HTTP/WebSocket 只读采集与归一化
      analytics/    PnL Engine、Feature Engine、SmartScore、统计回测
                    Signal Engine、Paper Trading Engine、纸面 PnL
      db/           PostgreSQL schema、迁移与各领域 repository
      api/          wallet、market、score、alert、watchlist、paper 接口
      core/         配置、日志、run_id
    scripts/        迁移、采集、回填、PnL、价格归档、评分、告警、性能验收
    tests/          数据合同、归一化、分析逻辑、schema 与 API 行为测试
  frontend/         Next.js Dashboard、钱包详情、市场详情、告警和 watchlist
  docs/             数据字典、阶段报告、ADR、验收报告和样例
  infra/            PostgreSQL、Redis、backend 的 Docker Compose 配置
```

技术栈：Python、FastAPI、Pydantic、httpx、SQLAlchemy、psycopg、PostgreSQL、Next.js、TypeScript、Docker Compose。Redis 已配置但业务暂未使用；未使用 TimescaleDB 特性。

## 已完成能力

### 基础与数据合同

- FastAPI、配置、结构化日志、run_id、集中式 schema 迁移和 Docker Compose 已完成。
- 金额、价格、size 使用 `Decimal`；CLOB token id 使用字符串；时间统一为 UTC。
- 原始 API 响应、标准化实体、ingestion run 和 checkpoint 均可追踪。

### 市场采集

- 已验证 Gamma、Data、CLOB HTTP 和 CLOB market WebSocket。
- 已实现 events、markets、outcome/token 映射、OI、live volume、liquidity、holders 和 raw response 入库。
- Gamma 使用 keyset 分页；token/outcome 长度不一致会标记映射失败，不静默猜测。

### 钱包发现与回填

- 候选来源包括 leaderboard、market holders 和近期 active traders。
- 已回填 trades、current positions、closed positions；`/trades` 使用 `takerOnly=false`。
- `trade_uid` 可稳定去重；checkpoint 支持按钱包和端点续跑，单钱包失败不会中断整批。

### PnL 与钱包画像

- PnL Engine v1 按 wallet/condition/token/outcome 聚合交易和仓位。
- 已生成 `wallet_market_results`、`wallet_daily_equity` 和 `pnl_reconciliation_checks`。
- 钱包画像区分 realized PnL、unrealized PnL、current value、ROI、profit factor、drawdown 和市场集中度。

### 价格、订单簿、CLV 与可跟随性

- 已实现 `prices-history` 回填、订单簿快照、多轮采样和 WebSocket 事件归档。
- 已落库 bid/ask、midpoint、spread、spread bps、top depth 和有限档深度。
- 已实现 signed CLV（30s、2m、10m、1h、24h）、保守滑点估算和 `market_liquidity_score`。
- WebSocket 同时保存系统 `received_at` 与 payload `event_at`，延迟分析优先使用 `received_at`。

### SmartScore 与回测

- Feature Engine v1、SmartScore v1、硬门槛、惩罚项、confidence 和组件拆解均已版本化落库。
- 评分覆盖收益质量、预测质量、时机优势、稳定性、可跟随性；网络信号当前为中性占位。
- 回测 v1 比较 `top_score`、`top_pnl`、`random_active` 三类选择策略。
- 小样本高 ROI、单市场暴利和正 CLV 但短期亏损等关键行为已有测试。

### API、Dashboard、watchlist 与告警

- Dashboard 提供钱包榜、市场监控、回测摘要和告警中心。
- 钱包详情包含评分拆解、hard gates、PnL、收益曲线、市场、类别、CLV 和近期交易。
- 市场详情包含元数据、token 映射、订单簿、holders、smart-flow 和相关告警。
- API 列表使用统一分页：`limit`、`offset`、`returned`、`total`、`has_more`；金额接口声明 `USDC`，错误使用统一结构。
- watchlist 支持钱包/市场写入并记录操作者、时间、内容；告警支持 `open/ack/resolved`。
- 五类告警规则已实现：高分钱包新建仓、多个高分钱包同向进入、临近结束大额建仓、流动性恶化、采集延迟。
- 告警查询默认只读；规则通过 `POST /alerts/generate`、Dashboard 按钮或 `python -m backend.scripts.generate_alerts` 显式执行。

### 纸面跟单

- 五张 Week08 表覆盖 signal、订单、事件、仓位与 PnL，原始交易、合并信号、决策和最终归因可串联追踪。
- 加权跟单综合 SmartScore、类别代理、稳定性和 followability；同市场同 token 同方向信号可合并。
- 风险门槛覆盖低样本/分数、置信度、流动性、spread、新鲜度、延迟、市场状态、合规和预期优势。
- FOK/FAK/GTC 使用有限档订单簿模拟全量、部分、等待和过期状态，不默认成交。
- `/paper` 页面展示策略摘要、状态/拒单分布、订单和 signal；CLI 支持单次或受监督的重复运行。

## 未完成与技术债务

### 当前主线：Week08 长期采样

- Week08 已达到 100 条模拟订单，但均为历史扫描且因低置信被拒绝；尚无实时可成交和 PnL 样本。
- “连续运行 7 天”尚未完成，不能进入 Week09 真实执行。
- 需要持续归档 watchlist token 订单簿并周期运行纸面 CLI，再验收 net ROI、win rate、max drawdown 和失败恢复。

### 数据与分析债务

- 24 小时 watchlist 订单簿/WebSocket 长跑尚未执行；followability 和 CLV 覆盖不足，是高置信钱包为 0 的主要原因。
- PnL v1 的 `estimated_slippage` 尚未用已归档订单簿回写。
- 回测使用当前历史结果做近似时间切分；严格历史重放需要按 cutoff 重建特征、仓位和订单簿快照。
- SmartScore 网络信号仍为中性占位；资金来源和协同行为等待后续链上索引与钱包聚类。
- maker/taker 双侧钱包归因尚未建模；`takerOnly=false` 不能证明单笔 maker/taker 角色。
- 负风险、组合型市场和多 outcome 市场尚未深入建模。
- Gamma 缺失 category/tag 时当前仅保留并告警，分类来源仍需补强。
- raw response 已归档，但 market/event/trade/position/holder/orderbook 的细粒度 schema contract 测试仍不足。
- `outcome_correct` 只有在 closed position 证据充分时才设置；其余保持 null。
- Daily equity 仍是 UTC 日级而非 tick 级。
- smart-flow 依赖最新评分和仓位快照，尚无全局 freshness SLA。

### 产品与生产化债务

- Dashboard 仅用于本地研究，没有登录和用户权限隔离。
- 告警已有独立 CLI，但尚未部署定时调度器；也没有任务队列、失败重试编排和运行监控。
- 尚未完成生产级限流、缓存策略、指标监控、部署脚本和备份恢复流程。
- Redis 尚未接入；当前数据量下查询无需缓存即可满足 p95，数据放大后需重新评估。
- VPS 尚未部署正式采集节点。
- 前端缺少浏览器端 E2E/视觉回归测试；后端测试中的 1 个 warning 来自 TestClient/httpx 第三方弃用提示。
- 真实执行、风控、人工确认和受控自动执行均未实现；在纸面结果稳定前不得推进真实下单。

## 必须遵守的口径

- `data/live-volume.id` 是 Gamma market 数值 id，不是 `condition_id` 或 CLOB token id。
- token 映射按 `clobTokenIds` 与 `outcomes` 的顺序建立，不允许按文本猜测。
- `prices-history` 不是历史订单簿；不能用最后成交价声称精确可成交或精确滑点。
- 滑点和可跟随性优先使用订单簿、spread、depth 和数据新鲜度。
- 未归档 token 的 followability 必须保守处理；Dashboard 必须继续展示 confidence、failed gates 和原因。

## 最小运行手册

```bash
cd /home/lee/workspace/search/codes
. .venv/bin/activate

# 基础验证与数据库
ruff check .
pytest -q
docker compose -f infra/docker-compose.yml up -d postgres
python -m backend.scripts.db_migrate

# 核心离线流水线
python -m backend.scripts.ingest_market_data --max-markets 5 --page-limit 5
python -m backend.scripts.backfill_wallet_data --candidate-limit 5 --backfill-wallet-limit 1 --max-trade-pages 1
python -m backend.scripts.calculate_pnl --wallet-limit 5 --profile-limit 2
python -m backend.scripts.archive_price_data --token-limit 5 --calculate-clv --clv-limit 1000
python -m backend.scripts.score_wallets --wallet-limit 150 --leaderboard-limit 100 --backtest
python -m backend.scripts.generate_alerts
python -m backend.scripts.run_paper_trading --lookback-minutes 60 --order-type FAK

# API 与验收
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
python -m backend.scripts.benchmark_dashboard --requests 30 --warmup 3

# 前端；当前环境默认 npm 指向 Windows，使用容器内 Linux Node
cd frontend
PATH=/home/lee/.vscode-remote-containers/bin/618725e67565b290ba4da6fe2d29f8fa1d4e3622:$PATH \
  NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 \
  node node_modules/next/dist/bin/next dev -H 127.0.0.1 -p 3000
```

## 关键文档

- `docs/data-dictionary.md`：数据库字段和口径。
- `docs/pnl-engine-report.md`：PnL v1 设计与限制。
- `docs/price-archive-report.md`：价格、订单簿、CLV、followability。
- `docs/smart-score-report.md`：SmartScore 和回测。
- `docs/week07-acceptance-report.md`：API、Dashboard、告警和性能验收。
- `docs/week08-acceptance-report.md`：纸面系统代码、真实 smoke、样本与长期验收状态。
- `../polymarket-wallet-tracker-plan/Week08-纸面跟单系统.md`：本阶段任务与验收标准。

## 下一会话建议顺序

1. 由进程监督器每分钟运行纸面周期，保留至少 7 天运行记录，不需要人工修复失败周期。
2. 同步持续归档 watchlist token 的订单簿和 WebSocket，避免所有信号停在 stale/low-liquidity 门槛。
3. 每日检查 `/paper` 的成交、拒单和延迟分布；没有实时成交样本时不得解释 ROI。
4. 为 category expertise 建立独立钱包分类特征，并校准市场费用模型。
5. 只有纸面结果在 2-4 周内稳定，才讨论 Week09；目前不得接入私钥或真实订单。
