# Week08 纸面跟单系统验收报告

验收时间：2026-07-10

## 结论

Week08 的代码闭环已完成：公开交易信号可以被标准化、加权和合并，经风险门槛后生成 FOK/FAK/GTC 模拟订单，逐档读取已归档订单簿，记录订单事件、分段延迟、模拟仓位和费用后 PnL，并由 API 与 Dashboard 展示。系统不持有私钥，不连接真实下单端点。

时间型验收仍需继续观察：当前完成 1 个真实数据库周期和 100 个模拟订单，尚未达到连续运行 7 天。不能据此宣称策略已有稳定收益。

## 交付内容

- 新增 `signals`、`paper_orders`、`paper_order_events`、`paper_positions`、`paper_pnl` 五张表，状态、拒单原因和关键字段均有数据库约束。
- Signal Engine v1 支持高分钱包与 watchlist 钱包交易，权重包含 SmartScore、类别专长代理、近期稳定性和 followability；同市场、同 token、同方向的多钱包信号可合并并保留子信号关系。
- Paper Trading Engine v1 实现低样本/低分、低置信、低流动性、宽 spread、陈旧数据、延迟信号、停止接单、合规阻断和负预期优势门槛。
- FOK 必须全量可成交，FAK 允许部分成交，GTC 在无立即成交时保持 `created` 并可在后续周期过期；所有状态变更写入事件表。
- 逐档订单簿模拟记录 worst price、加权成交价、成交量、滑点和估算费用，不把价格历史误当订单簿。
- 延迟拆分为 leader trade → signal、signal → decision、decision → simulation 三段。
- PnL 区分 gross PnL、fee、slippage cost、net PnL、方向正确和费用后盈利；市场结算后可将订单、仓位推进为 settled。
- 新增 `/paper/summary`、`/paper/signals`、`/paper/orders`、`/paper/run`，以及 `/paper` Dashboard 页面和手动模拟按钮。
- CLI 支持单周期和重复周期；长期运行应交给 systemd、Docker restart policy 或其他进程监督器。

## 自动化验证

- `pytest -q`：75 passed，1 个既有 TestClient/httpx 弃用提示。
- `ruff check .`：通过。
- Next.js production build：通过，包含动态路由 `/paper`。
- PostgreSQL schema 迁移：`2026_07_10_week08_paper_trading_schema_v1` 已成功应用。
- 真实 API smoke：summary、signal 列表和 order 列表均返回 200，分页、金额单位和拒单证据可读。

## 当前真实样本

- 周期数：1；失败周期：0。
- signal：100；模拟订单：100。
- 订单状态：100 rejected；0 would_fill；0 would_partial_fill。
- 拒单分布：100 `low_confidence`。
- 样本来源是当前 watchlist 钱包的历史公开交易；该钱包最新 confidence 为 0.2008，低于策略门槛 0.35。
- 因为全部在置信度门槛被拒绝，没有 paper position、可估值订单或 PnL。此结果证明当前样本不应跟单，而不是收益为零的策略结论。

## 未完成和风险

- 连续 7 天运行尚未完成；需要保留周期日志、失败次数和数据新鲜度后再验收稳定性。
- 虽已达到 100 个模拟订单，但它们来自历史扫描且全部被低置信拒绝；实时成交质量仍无样本。
- 当前类别专长使用评分置信度作为保守代理，后续应建立钱包 × category 的独立表现特征。
- 当前费用采用版本化固定费率假设；不同市场的实际费率模型需要进一步校准。
- 订单簿覆盖不足仍是成交和收益样本缺失的主要限制。应先持续归档 watchlist token，再评估纸面 ROI、win rate 和 max drawdown。
