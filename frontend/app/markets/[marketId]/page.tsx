import Link from "next/link";
import { notFound } from "next/navigation";

import { AlertActions } from "@/components/AlertActions";
import { WatchlistForm } from "@/components/WatchlistForm";
import { decimal, getJson, isoDate, money, shortId } from "@/lib/api";

type Row = Record<string, any>;

type MarketDetailResponse = {
  detail: {
    market: Row;
    tokens: Row[];
    latest_orderbook: Row[];
    top_holders: Row[];
    smart_wallet_positions: Row[];
    alerts: Row[];
  };
};

type SmartFlowResponse = {
  smart_flow: Row[];
};

export default async function MarketPage({ params }: { params: Promise<{ marketId: string }> }) {
  const { marketId } = await params;
  const [detailResult, flowResult] = await Promise.all([
    getJson<MarketDetailResponse>(`/markets/${encodeURIComponent(marketId)}`),
    getJson<SmartFlowResponse>(`/markets/${encodeURIComponent(marketId)}/smart-flow?limit=100`),
  ]);

  if (!detailResult.data && detailResult.error?.startsWith("404")) {
    notFound();
  }

  const detail = detailResult.data?.detail;
  const market = detail?.market ?? {};
  const tokens = detail?.tokens ?? [];
  const orderbook = detail?.latest_orderbook ?? [];
  const holders = detail?.top_holders ?? [];
  const smartFlow = flowResult.data?.smart_flow ?? detail?.smart_wallet_positions ?? [];
  const alerts = detail?.alerts ?? [];

  return (
    <main className="shell">
      <div className="detail-title">
        <div>
          <div className="eyebrow">Market</div>
          <h1>{market.question ?? shortId(marketId, 12, 8)}</h1>
        </div>
        <Link className="button" href="/">
          Dashboard
        </Link>
      </div>

      {detailResult.error ? <div className="error">{detailResult.error}</div> : null}

      <section className="hero">
        <div className="section">
          <div className="section-header">
            <div>
              <div className="eyebrow">Overview</div>
              <h2>Market metadata</h2>
            </div>
            <span className={`pill ${market.active ? "good" : "warn"}`}>
              {market.active ? "active" : market.closed ? "closed" : "inactive"}
            </span>
          </div>
          <div className="metric-grid">
            <Metric label="Volume" value={money(market.volume)} note="USDC notional" />
            <Metric label="Liquidity" value={money(market.liquidity)} note="reported liquidity" />
            <Metric label="Tokens" value={tokens.length} note={market.category ?? "unknown category"} />
            <Metric label="End" value={isoDate(market.end_date)} note={market.accepting_orders ? "orders open" : "orders closed"} />
          </div>
        </div>

        <div className="section">
          <div className="section-header">
            <div>
              <div className="eyebrow">Watchlist</div>
              <h2>Market tracking</h2>
            </div>
          </div>
          <WatchlistForm kind="market" targetId={market.condition_id ?? marketId} />
        </div>
      </section>

      <section className="grid">
        <div className="stack">
          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Orderbook</div>
                <h2>Current price, spread, and depth</h2>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Outcome</th>
                    <th>Bid</th>
                    <th>Ask</th>
                    <th>Mid</th>
                    <th>Spread</th>
                    <th>Bid depth</th>
                    <th>Ask depth</th>
                    <th>Follow</th>
                  </tr>
                </thead>
                <tbody>
                  {orderbook.map((row) => (
                    <tr key={row.asset_id}>
                      <td>{row.outcome ?? shortId(row.asset_id)}</td>
                      <td>{decimal(row.best_bid, 3)}</td>
                      <td>{decimal(row.best_ask, 3)}</td>
                      <td>{decimal(row.midpoint, 3)}</td>
                      <td>{decimal(row.spread_bps, 0)} bps</td>
                      <td>{money(row.top_bid_depth)}</td>
                      <td>{money(row.top_ask_depth)}</td>
                      <td>{decimal(row.market_liquidity_score, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Smart flow</div>
                <h2>High-score wallet positions</h2>
              </div>
              <span className="pill">{smartFlow.length} rows</span>
            </div>
            {flowResult.error ? <div className="error">{flowResult.error}</div> : null}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Wallet</th>
                    <th>Score</th>
                    <th>Confidence</th>
                    <th>Outcome</th>
                    <th>Current value</th>
                    <th>Recent notional</th>
                  </tr>
                </thead>
                <tbody>
                  {smartFlow.map((row, index) => (
                    <tr key={`${row.wallet_address}-${row.token_id}-${index}`}>
                      <td>
                        <Link className="link" href={`/wallets/${row.wallet_address}`}>
                          {shortId(row.wallet_address)}
                        </Link>
                      </td>
                      <td>{decimal(row.score, 1)}</td>
                      <td>{decimal(row.confidence, 2)}</td>
                      <td>{row.outcome ?? shortId(row.token_id)}</td>
                      <td>{money(row.current_value)}</td>
                      <td>{money(row.recent_notional)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="stack">
          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Mapping</div>
                <h2>Outcome tokens</h2>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Outcome</th>
                    <th>Token</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {tokens.map((token) => (
                    <tr key={token.token_id}>
                      <td>{token.outcome ?? token.outcome_index}</td>
                      <td>{shortId(token.token_id, 8, 6)}</td>
                      <td>{token.mapping_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Holders</div>
                <h2>Top holders</h2>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Wallet</th>
                    <th>Token</th>
                    <th>Amount</th>
                    <th>Rank</th>
                  </tr>
                </thead>
                <tbody>
                  {holders.slice(0, 12).map((holder) => (
                    <tr key={`${holder.wallet_address}-${holder.token_id}`}>
                      <td>{shortId(holder.wallet_address)}</td>
                      <td>{shortId(holder.token_id)}</td>
                      <td>{decimal(holder.amount, 2)}</td>
                      <td>{holder.holder_rank ?? "n/a"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Alerts</div>
                <h2>Related alerts</h2>
              </div>
            </div>
            {alerts.length ? (
              alerts.map((alert) => (
                <div className="alert-row" key={alert.alert_id}>
                  <div>
                    <div className="alert-title">{alert.title}</div>
                    <div className="alert-message">{alert.message}</div>
                  </div>
                  <AlertActions alertId={alert.alert_id} initialStatus={alert.status} />
                </div>
              ))
            ) : (
              <div className="empty">No related alerts.</div>
            )}
          </div>
        </div>
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
