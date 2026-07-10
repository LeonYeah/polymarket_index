# Week06 SmartScore 与统计回测报告

> 本文记录最初的 `smart_score_v1` 验收口径。当前写入版本已升级为
> `smart_score_v2`；v2 变更见 `docs/smart-score-v2-report.md`，历史 v1 行不会被覆盖。

日期：2026-07-09

## 范围

已实现 SmartScore v1、硬门槛、惩罚项、版本化评分表、组件拆分表、统计回测表、排行榜 CLI 和 API。

入口：

```bash
python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20
python -m backend.scripts.score_wallets --wallet-limit 100 --leaderboard-limit 20 --backtest --strategy-size 10 --validation-days 30
curl 'http://127.0.0.1:8000/scores/leaderboard?limit=50'
```

## 评分口径

SmartScore v1 使用可解释规则分，不引入 ML。

组件权重：

| 组件 | 权重 |
|---|---:|
| 收益质量 | 25 |
| 预测质量 | 25 |
| 时机优势 | 20 |
| 稳定性 | 15 |
| 可跟随性 | 10 |
| 网络信号 | 5 |

硬门槛：

- `n_resolved >= 50`
- `active_days_180d >= 30`
- `realized_notional_180d >= 25000`
- `net_roi_180d >= 8%`
- `bayes_wr >= 55%`
- `max_drawdown_ratio <= 20%`
- `single_market_pnl_share <= 30%`
- `avg_followability >= 60`

惩罚项：

- `n_resolved < 20` 总分封顶 60。
- `n_resolved < 50` 总分封顶 75。
- 单市场利润占比超过 50% 扣 10-25 分。
- 低流动性交易占比超过 50% 扣最多 10 分。
- 未结算浮盈占比过高会降低 confidence。

## 表结构

新增表：

- `wallet_features`
- `wallet_scores`
- `wallet_score_components`
- `backtest_runs`
- `backtest_wallet_results`

每次评分保存 `score_version`、`feature_version`、`weight_config`、`input_snapshot`、`hard_gate_status`、`exclusion_reasons` 和组件明细，便于复现。

## Smoke 验收

命令：

```bash
python -m backend.scripts.db_migrate
python -m backend.scripts.score_wallets --wallet-limit 5 --leaderboard-limit 5 --backtest --strategy-size 2 --validation-days 7
```

结果：

- schema migration：`2026_07_09_week06_smart_score_schema_v1`
- `feature_rows=5`
- `scores=5`
- `leaderboard_rows=5`
- `backtest_wallet_results=6`
- 三类策略均有输出：`top_score`、`top_pnl`、`random_active`

当前 5 钱包 smoke 没有高置信钱包，主要原因是 followability 数据覆盖不足或样本量不足。这是合理结果，不应强行放宽门槛。

## 测试

当前验证：

- `pytest -q`：46 passed、1 warning
- `ruff check .`：通过

新增测试覆盖：

- 小样本高 ROI 钱包不会进入高置信榜首，并触发封顶。
- 单市场暴利钱包被惩罚。
- 长期正 CLV 但短期亏损的钱包保留预测质量信号。
- 回测策略覆盖 Top score、Top PnL、随机活跃钱包。
- Week06 schema 和可复现字段存在性。

## 已知限制

- 回测使用现有表中可获得的历史结果近似时间切分；若上游数据本身只保留当前快照，仍可能缺少完整历史状态。
- followability 依赖 Week05 订单簿归档覆盖；未归档 token 的钱包会被保守评为低可跟随性。
- 网络信号 Week06 仅为中性占位，资金来源和协同行为留到 Week11 链上索引与聚类阶段。
- SmartScore 是研究指标，不是收益承诺。
