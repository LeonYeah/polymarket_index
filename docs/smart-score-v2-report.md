# SmartScore v2 与持续候选发现

日期：2026-07-10

## 变更结论

- 当前评分写入版本升级为 `smart_score_v2`，继续复用未发生字段变化的
  `wallet_features_v1` 特征合同。
- 删除 `single_market_pnl_share <= 30%` 高置信 hard gate。
- 单市场利润占比超过 50% 的软扣分保持不变，用于抑制单次暴利样本，但不再单独取消
  高置信资格。
- v1 分数、组件和回测数据保留；v2 使用新的 `score_version` 和 source 写入，便于对照审计。

## V2 hard gates

- `n_resolved >= 50`
- `active_days_180d >= 30`
- `realized_notional_180d >= 25000`
- `net_roi_180d >= 8%`
- `bayes_wr >= 55%`
- `max_drawdown_ratio <= 20%`
- `avg_followability >= 60`

## 持续候选发现

VPS 的 6 小时 maintenance 按以下顺序执行：

1. 刷新市场和有限范围 holders。
2. 从 DAY/WEEK/MONTH/ALL leaderboard、holders 和最新 active traders 幂等发现候选。
3. 每轮最多回填 25 个优先钱包；每个钱包最多 2 页交易，并刷新 current/closed positions。
4. 更新 PnL。
5. 生成 SmartScore v2。

候选发现是低频维护任务，不进入每分钟 sampler。单阶段失败会被记录，但不会阻止后续阶段
使用上一份数据库快照继续运行。

## 验证重点

- 高集中钱包仍产生 `single_market_profit_concentration` penalty。
- 在其他 hard gates 全部通过时，高集中钱包不再因 30% 单市场占比被排除。
- maintenance 在 PnL 和评分前运行候选发现，并将回填批次限制为 25 个钱包。
- 候选 API 暂时失败时，PnL 和 SmartScore 仍会继续执行。
