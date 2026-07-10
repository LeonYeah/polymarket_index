# VPS 连续采样运行手册

部署时间：2026-07-10

## 架构与安全边界

- 主机：`ssh usa`，Ubuntu 24.04，2 vCPU、3.8 GiB RAM、38 GiB 磁盘。
- 代码：`/opt/polymarket-wallet-tracker`。
- 运行用户：无登录 shell 的 `polymarket` 系统用户。
- 数据库：原生 PostgreSQL 16，数据库与角色均为 `polymarket`，通过本地 Unix socket peer 认证，不保存数据库密码。
- PostgreSQL 仅监听 `127.0.0.1` 和 `::1`；FastAPI 仅监听 `127.0.0.1:8000`。
- 不保存私钥、签名凭证、交易 cookie 或真实下单 API key。
- 443 端口仍由原有 `sing-box` 使用，本项目没有修改或占用该端口。

## systemd 单元

| 单元 | 类型 | 用途 |
|---|---|---|
| `polymarket-api.service` | 常驻 | 本地回环 FastAPI。 |
| `polymarket-sampler.service` | 常驻 | 每分钟执行增量交易、相关订单簿和 paper cycle。 |
| `polymarket-maintenance.timer` | 6 小时 | 刷新市场元数据、PnL 和 SmartScore。 |
| `polymarket-health.timer` | 5 分钟 | 检查连续周期是否在 300 秒 freshness SLA 内。 |
| `polymarket-backup.timer` | 每日 | PostgreSQL custom dump，保留 14 天。 |

查看状态：

```bash
ssh usa 'systemctl status polymarket-api polymarket-sampler --no-pager'
ssh usa 'systemctl list-timers --all --no-pager | grep polymarket'
ssh usa 'journalctl -u polymarket-sampler -n 50 --no-pager'
```

健康检查：

```bash
ssh usa 'curl -fsS http://127.0.0.1:8000/paper/health'
ssh usa 'cd /opt/polymarket-wallet-tracker && \
  sudo -u polymarket .venv/bin/python -m backend.scripts.check_sampling_health \
  --max-age-seconds 300 --allow-degraded'
```

## 本地访问 VPS Dashboard 数据

保持一个 SSH 隧道终端：

```bash
ssh -N -L 8001:127.0.0.1:8000 usa
```

另一个终端启动本地前端：

```bash
cd /home/lee/workspace/search/codes/frontend
PATH=/home/lee/.vscode-remote-containers/bin/618725e67565b290ba4da6fe2d29f8fa1d4e3622:$PATH \
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 \
node node_modules/next/dist/bin/next dev -H 127.0.0.1 -p 3000
```

随后访问 `http://127.0.0.1:3000/paper`。不要把 VPS 的 8000 或 5432 端口开放到公网。

## 数据采样语义

连续周期按以下顺序运行：

1. 对 watchlist 和合格高分钱包始终从 Data API `/trades` offset 0 拉取最新页，避免历史 backfill exhausted checkpoint 漏掉新交易。
2. 从 watchlist 市场、目标钱包近期交易和 pending signal 选择相关 token。
3. 对 token 采集当前 CLOB `/book`，计算有限档深度与 followability。
4. 运行 FAK paper cycle，记录 signal、拒单/模拟成交、延迟、仓位和 PnL。
5. CLOB 失败 token 冷却 15 分钟后自动重试，避免每分钟重复请求已失效 book。

最后一次部署重启后，连续验收起点为 `2026-07-10 04:01:49 UTC`。在至少运行至 `2026-07-17 04:01:49 UTC` 且 freshness、失败周期和数据质量复核通过前，不宣称完成 7 天验收。

## 备份与恢复

备份目录：`/var/backups/polymarket`，仅 `postgres` 可读。

手动备份：

```bash
ssh usa 'systemctl start polymarket-backup.service'
```

校验归档：

```bash
ssh usa 'sudo -u postgres pg_restore --list /var/backups/polymarket/<dump-file>'
```

恢复前应先停止 API、sampler 和 timers，创建空数据库，再以 `polymarket` 身份执行 `pg_restore --no-owner --no-acl`。恢复属于破坏性操作，必须先保留当前数据库备份。

## 代码更新

本地代码提交并通过测试后，用 rsync 排除运行时目录同步到 VPS；随后恢复 root 所有权并仅重启受影响服务。VPS 部署目录应保持 Git clean，服务用户不得修改代码。

每次更新至少验证：

```bash
ssh usa 'cd /opt/polymarket-wallet-tracker && .venv/bin/pytest -q -p no:cacheprovider'
ssh usa 'cd /opt/polymarket-wallet-tracker && .venv/bin/ruff check --no-cache .'
ssh usa 'curl -fsS http://127.0.0.1:8000/health'
ssh usa 'curl -fsS http://127.0.0.1:8000/paper/health'
```
