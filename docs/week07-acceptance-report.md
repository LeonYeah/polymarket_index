# Week07 API、Dashboard 与提醒验收报告

验收时间：2026-07-10（UTC+8）

## 结论

Week07 工程交付物和本地 MVP 验收项已完成。长期数据覆盖不作为本次阻塞项，继续保留研究数据债务。

## 功能验收

- FastAPI 已提供钱包榜、钱包详情、钱包市场、市场列表、市场详情、smart-flow、告警、watchlist 和回测摘要接口。
- Next.js 已提供 Dashboard、钱包详情页、市场详情页、告警操作和 watchlist 表单。
- 排行榜使用现有数据生成 150 个钱包分数，`GET /wallets/top?limit=100` 实际返回 100 行。
- 数据库已有 500 个市场，`GET /markets?limit=100` 实际返回 100 行。
- API 分页统一返回 `limit`、`offset`、`returned`、`total`、`has_more`。
- 金额接口返回 `amount_units=USDC`，时间字段经 API 输出为 ISO 8601 UTC。
- API 错误统一返回 `error.code`、`error.message`、`error.details` 和 `timestamp_utc`。

## 告警与审计验收

- 告警规则 CLI 实际生成 5 条 `ingestion_delay` 告警。
- 对真实告警完成 `open -> ack -> resolved` 状态流转，确认和关闭时间均已记录。
- 对一个钱包和一个市场完成 watchlist 写入，审计表新增 2 条操作者为 `acceptance-test` 的记录。
- 告警查询默认只读；规则可通过 `POST /alerts/generate`、Dashboard 按钮或 `python -m backend.scripts.generate_alerts` 显式运行。

## 性能验收

本地 PostgreSQL 数据：150 个最新评分钱包、500 个市场。每个接口预热 3 次后请求 30 次：

| API | 返回行数 | p50 | p95 | 阈值 |
| --- | ---: | ---: | ---: | ---: |
| `/wallets/top?limit=100` | 100 | 30.554 ms | 36.070 ms | 500 ms |
| `/markets?limit=100` | 100 | 26.745 ms | 49.812 ms | 500 ms |
| `/alerts?limit=100&generate=false` | 4 open | 19.780 ms | 23.205 ms | 500 ms |

所有被测接口 p95 均低于 500ms。当前查询无需缓存即可满足本地验收阈值；若数据量增长导致退化，再引入 Redis 或后台物化刷新。

复测命令：

```bash
python -m backend.scripts.benchmark_dashboard --requests 30 --warmup 3
```

## 自动化验证

- `ruff check .`：通过。
- `pytest -q`：54 passed，1 个第三方弃用警告。
- Next.js production build：通过。

## 暂缓的长期数据项

- 当前高置信钱包仍为 0，主要受订单簿/followability 和 CLV 历史覆盖不足影响；Dashboard 明确展示低置信状态和失败门槛。
- 五类告警规则均已实现，但现有快照只实际触发采集延迟规则；其他规则需要后续持续采集产生满足阈值的数据。
- 严格历史状态重放、24 小时订单簿长跑和生产级调度部署留在后续周任务，不阻塞 Week07 本地 MVP 验收。
