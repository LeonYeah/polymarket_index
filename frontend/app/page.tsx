import Link from "next/link";

import { AlertActions } from "@/components/AlertActions";
import { decimal, getJson, isoDate, money, pct, shortId } from "@/lib/api";

type Row = Record<string, any>;

type WalletsResponse = {
  wallets: Row[];
  pagination: { returned: number };
};

type MarketsResponse = {
  markets: Row[];
  pagination: { returned: number };
};

type AlertsResponse = {
  alerts: Row[];
  generated: Record<string, number>;
};

type BacktestResponse = {
  backtest: Row;
};

export default async function DashboardPage() {
  const [walletsResult, marketsResult, alertsResult, backtestResult] = await Promise.all([
    getJson<WalletsResponse>("/wallets/top?limit=100&high_confidence_only=false"),
    getJson<MarketsResponse>("/markets?limit=100"),
    getJson<AlertsResponse>("/alerts?limit=50&status=open&generate=true"),
    getJson<BacktestResponse>("/scores/backtests/latest"),
  ]);

  const wallets = walletsResult.data?.wallets ?? [];
  const markets = marketsResult.data?.markets ?? [];
  const alerts = alertsResult.data?.alerts ?? [];
  const backtest = backtestResult.data?.backtest ?? {};
  const eligible = wallets.filter((wallet) => wallet.high_confidence_eligible).length;
  const smartFlowMarkets = markets.filter((market) => Number(market.smart_wallet_count ?? 0) > 0).length;
  const totalGenerated = Object.values(alertsResult.data?.generated ?? {}).reduce(
    (sum, value) => sum + Number(value ?? 0),
    0,
  );

  return (
    <main className="shell">
      <section className="hero">
        <div className="market-map">
          <div className="map-inner">
            <span className="map-point" />
            <span className="map-point" />
            <span className="map-point" />
            <span className="map-point" />
            <div className="headline">
              <div className="eyebrow">Read-only research dashboard</div>
              <h1>SmartScore wallet ranking, market flow, and alert review.</h1>
              <p>
                Realized PnL, current value, CLV, liquidity, hard gates, and backtest evidence are
                displayed as separate fields.
              </p>
            </div>
          </div>
        </div>
        <div className="metric-grid">
          <Metric label="Wallets" value={wallets.length} note={`${eligible} high confidence`} />
          <Metric label="Markets" value={markets.length} note={`${smartFlowMarkets} with smart flow`} />
          <Metric label="Open Alerts" value={alerts.length} note={`${totalGenerated} generated`} />
          <Metric
            label="Backtest"
            value={Object.keys(backtest).length ? String(backtest.status ?? "ready") : "none"}
            note={shortId(backtest.backtest_run_uid ?? "no run", 10, 4)}
          />
        </div>
      </section>

      <section className="grid">
        <div className="section">
          <div className="section-header">
            <div>
              <div className="eyebrow">Scores</div>
              <h2>Wallet leaderboard</h2>
            </div>
            <span className="pill">{wallets.length} rows</span>
          </div>
          {walletsResult.error ? <div className="error">{walletsResult.error}</div> : null}
          {wallets.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Wallet</th>
                    <th>Score</th>
                    <th>Conf.</th>
                    <th>Realized PnL</th>
                    <th>ROI</th>
                    <th>Resolved</th>
                    <th>Follow</th>
                    <th>Gate</th>
                  </tr>
                </thead>
                <tbody>
                  {wallets.map((wallet) => (
                    <tr key={wallet.wallet_address}>
                      <td>{wallet.rank}</td>
                      <td>
                        <Link className="link" href={`/wallets/${wallet.wallet_address}`}>
                          {shortId(wallet.wallet_address)}
                        </Link>
                      </td>
                      <td>{decimal(wallet.score, 1)}</td>
                      <td>{decimal(wallet.confidence, 2)}</td>
                      <td>{money(wallet.realized_pnl_180d)}</td>
                      <td>{pct(wallet.net_roi_180d)}</td>
                      <td>{wallet.n_resolved ?? 0}</td>
                      <td>{decimal(wallet.avg_followability, 1)}</td>
                      <td>
                        <span className={`pill ${wallet.high_confidence_eligible ? "good" : "warn"}`}>
                          {wallet.high_confidence_eligible ? "pass" : "review"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty">No wallet rows returned.</div>
          )}
        </div>

        <div className="stack">
          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Alerts</div>
                <h2>Alert center</h2>
              </div>
              <span className="pill warn">{alerts.length} open</span>
            </div>
            {alertsResult.error ? <div className="error">{alertsResult.error}</div> : null}
            {alerts.length ? (
              alerts.slice(0, 8).map((alert) => (
                <div className="alert-row" key={alert.alert_id}>
                  <div>
                    <div className="alert-title">{alert.title}</div>
                    <div className="alert-message">{alert.message}</div>
                    <div className="alert-message">{isoDate(alert.last_seen_at)}</div>
                  </div>
                  <AlertActions alertId={alert.alert_id} initialStatus={alert.status} />
                </div>
              ))
            ) : (
              <div className="empty">No open alerts.</div>
            )}
          </div>

          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Backtest</div>
                <h2>Latest strategy comparison</h2>
              </div>
              <span className="pill">{String(backtest.status ?? "none")}</span>
            </div>
            {backtestResult.error ? <div className="error">{backtestResult.error}</div> : null}
            {Object.keys(backtest).length ? (
              <BacktestBars summary={backtest.summary ?? {}} />
            ) : (
              <div className="empty">No backtest run found.</div>
            )}
          </div>
        </div>
      </section>

      <section className="section" style={{ marginTop: 18 }}>
        <div className="section-header">
          <div>
            <div className="eyebrow">Markets</div>
            <h2>Market monitor</h2>
          </div>
          <span className="pill">{markets.length} rows</span>
        </div>
        {marketsResult.error ? <div className="error">{marketsResult.error}</div> : null}
        {markets.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Volume</th>
                  <th>Liquidity</th>
                  <th>Mid</th>
                  <th>Spread</th>
                  <th>Depth</th>
                  <th>Smart wallets</th>
                  <th>End</th>
                </tr>
              </thead>
              <tbody>
                {markets.map((market) => (
                  <tr key={market.condition_id}>
                    <td className="truncate">
                      <Link className="link" href={`/markets/${market.condition_id}`}>
                        {market.question ?? shortId(market.condition_id, 10, 6)}
                      </Link>
                    </td>
                    <td>{money(market.volume)}</td>
                    <td>{money(market.liquidity)}</td>
                    <td>{decimal(market.midpoint, 3)}</td>
                    <td>{decimal(market.spread_bps, 0)} bps</td>
                    <td>
                      {money(Number(market.top_bid_depth ?? 0) + Number(market.top_ask_depth ?? 0))}
                    </td>
                    <td>{market.smart_wallet_count ?? 0}</td>
                    <td>{isoDate(market.end_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">No market rows returned.</div>
        )}
      </section>
    </main>
  );
}

function Metric({ label, value, note }: { label: string; value: string | number; note: string }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}

function BacktestBars({ summary }: { summary: Record<string, Row> }) {
  const rows = Object.entries(summary);
  if (!rows.length) {
    return <div className="empty">No strategy rows.</div>;
  }
  const maxPnl = Math.max(
    1,
    ...rows.map(([, value]) => Math.abs(Number(value.avg_future_net_pnl ?? value.future_net_pnl ?? 0))),
  );
  return (
    <div className="bars">
      {rows.map(([strategy, value]) => {
        const pnl = Number(value.avg_future_net_pnl ?? value.future_net_pnl ?? 0);
        const width = Math.max(6, Math.round((Math.abs(pnl) / maxPnl) * 100));
        return (
          <div className="bar-row" key={strategy}>
            <span>{strategy}</span>
            <div className="bar">
              <span style={{ width: `${width}%` }} />
            </div>
            <strong>{money(pnl)}</strong>
          </div>
        );
      })}
    </div>
  );
}
