import Link from "next/link";
import { notFound } from "next/navigation";

import { WatchlistForm } from "@/components/WatchlistForm";
import { decimal, getJson, isoDate, money, pct, shortId } from "@/lib/api";

type Row = Record<string, any>;

type WalletDetailResponse = {
  wallet_address: string;
  detail: {
    summary: Row | null;
    score: Row | null;
    score_components: Row[];
    equity_curve: Row[];
    category_distribution: Row[];
    clv_distribution: Row;
    recent_trades: Row[];
    markets: Row[];
  };
};

export default async function WalletPage({ params }: { params: Promise<{ address: string }> }) {
  const { address } = await params;
  const result = await getJson<WalletDetailResponse>(
    `/wallets/${encodeURIComponent(address)}?market_limit=100&trade_limit=50`,
  );

  if (!result.data && result.error?.startsWith("404")) {
    notFound();
  }

  const detail = result.data?.detail;
  const summary = detail?.summary;
  const score = detail?.score;
  const components = detail?.score_components ?? [];
  const markets = detail?.markets ?? [];
  const equity = detail?.equity_curve ?? [];
  const categories = detail?.category_distribution ?? [];
  const trades = detail?.recent_trades ?? [];

  return (
    <main className="shell">
      <div className="detail-title">
        <div>
          <div className="eyebrow">Wallet</div>
          <h1>{shortId(result.data?.wallet_address ?? address, 12, 8)}</h1>
        </div>
        <Link className="button" href="/">
          Dashboard
        </Link>
      </div>

      {result.error ? <div className="error">{result.error}</div> : null}

      <section className="hero">
        <div className="section">
          <div className="section-header">
            <div>
              <div className="eyebrow">Overview</div>
              <h2>Score and PnL</h2>
            </div>
            <span className={`pill ${score?.high_confidence_eligible ? "good" : "warn"}`}>
              {score?.high_confidence_eligible ? "high confidence" : "review gates"}
            </span>
          </div>
          <div className="metric-grid">
            <Metric label="Score" value={decimal(score?.score, 1)} note={`conf. ${decimal(score?.confidence, 2)}`} />
            <Metric label="Realized PnL" value={money(summary?.realized_pnl)} note="closed positions" />
            <Metric label="Unrealized PnL" value={money(summary?.unrealized_pnl)} note="current positions" />
            <Metric label="Net ROI" value={pct(summary?.net_roi)} note={`max DD ${money(summary?.max_drawdown)}`} />
          </div>
        </div>

        <div className="section">
          <div className="section-header">
            <div>
              <div className="eyebrow">Watchlist</div>
              <h2>Wallet tracking</h2>
            </div>
          </div>
          <WatchlistForm kind="wallet" targetId={result.data?.wallet_address ?? address} />
        </div>
      </section>

      <section className="grid">
        <div className="stack">
          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Equity</div>
                <h2>Daily net curve</h2>
              </div>
              <span className="pill">{equity.length} days</span>
            </div>
            <Sparkline rows={equity} />
          </div>

          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Markets</div>
                <h2>Participated markets</h2>
              </div>
              <span className="pill">{markets.length} rows</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>Status</th>
                    <th>Outcome</th>
                    <th>Realized</th>
                    <th>Unrealized</th>
                    <th>ROI</th>
                  </tr>
                </thead>
                <tbody>
                  {markets.map((market) => (
                    <tr key={market.result_uid}>
                      <td className="truncate">
                        <Link className="link" href={`/markets/${market.condition_id}`}>
                          {market.question ?? shortId(market.condition_id, 10, 6)}
                        </Link>
                      </td>
                      <td>{market.result_status}</td>
                      <td>{market.outcome ?? "n/a"}</td>
                      <td>{money(market.realized_pnl)}</td>
                      <td>{money(market.unrealized_pnl)}</td>
                      <td>{pct(market.net_roi)}</td>
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
                <div className="eyebrow">Gates</div>
                <h2>Hard gate status</h2>
              </div>
            </div>
            <GateList score={score} />
          </div>

          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">Components</div>
                <h2>Score breakdown</h2>
              </div>
            </div>
            <ComponentBars rows={components} />
          </div>

          <div className="section">
            <div className="section-header">
              <div>
                <div className="eyebrow">CLV</div>
                <h2>Prediction quality</h2>
              </div>
              <span className="pill">{detail?.clv_distribution?.sample_count ?? 0} samples</span>
            </div>
            <div className="metric-grid">
              <Metric label="30s" value={decimal(detail?.clv_distribution?.avg_clv_30s, 4)} note="avg CLV" />
              <Metric label="10m" value={decimal(detail?.clv_distribution?.avg_clv_10m, 4)} note="avg CLV" />
              <Metric label="1h" value={decimal(detail?.clv_distribution?.avg_clv_1h, 4)} note="avg CLV" />
              <Metric
                label="Positive"
                value={pct(detail?.clv_distribution?.positive_clv_10m_share)}
                note="10m share"
              />
            </div>
          </div>
        </div>
      </section>

      <section className="two-col" style={{ marginTop: 18 }}>
        <div className="section">
          <div className="section-header">
            <div>
              <div className="eyebrow">Categories</div>
              <h2>Category distribution</h2>
            </div>
          </div>
          <CategoryBars rows={categories} />
        </div>
        <div className="section">
          <div className="section-header">
            <div>
              <div className="eyebrow">Trades</div>
              <h2>Recent trades</h2>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Market</th>
                  <th>Side</th>
                  <th>Price</th>
                  <th>Notional</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice(0, 12).map((trade) => (
                  <tr key={trade.trade_uid}>
                    <td>{isoDate(trade.trade_timestamp)}</td>
                    <td className="truncate">{trade.question ?? shortId(trade.condition_id, 10, 6)}</td>
                    <td>{trade.side ?? "n/a"}</td>
                    <td>{decimal(trade.price, 3)}</td>
                    <td>{money(trade.notional)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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

function Sparkline({ rows }: { rows: Row[] }) {
  if (!rows.length) {
    return <div className="empty">No equity rows.</div>;
  }
  const values = rows.map((row) => Number(row.net_pnl ?? 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = rows.length === 1 ? 0 : (index / (rows.length - 1)) * 100;
      const y = 100 - ((value - min) / span) * 86 - 7;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg aria-label="Daily net curve" role="img" viewBox="0 0 100 100" width="100%" height="180">
      <polyline fill="none" points={points} stroke="#176b4d" strokeWidth="2.5" />
    </svg>
  );
}

function GateList({ score }: { score: Row | null | undefined }) {
  const gates = Object.entries(score?.hard_gate_status ?? {});
  if (!gates.length) {
    return <div className="empty">No gate snapshot.</div>;
  }
  return (
    <div className="bars">
      {gates.map(([name, passed]) => (
        <div className="bar-row" key={name}>
          <span>{name}</span>
          <span className={`pill ${passed ? "good" : "bad"}`}>{passed ? "pass" : "fail"}</span>
          <strong />
        </div>
      ))}
    </div>
  );
}

function ComponentBars({ rows }: { rows: Row[] }) {
  if (!rows.length) {
    return <div className="empty">No component rows.</div>;
  }
  return (
    <div className="bars">
      {rows.map((row) => {
        const max = Number(row.max_score ?? 1);
        const value = Number(row.component_score ?? 0);
        const width = Math.max(4, Math.round((value / max) * 100));
        return (
          <div className="bar-row" key={row.component_name}>
            <span>{row.component_name}</span>
            <div className="bar">
              <span style={{ width: `${width}%` }} />
            </div>
            <strong>
              {decimal(value, 1)}/{decimal(max, 0)}
            </strong>
          </div>
        );
      })}
    </div>
  );
}

function CategoryBars({ rows }: { rows: Row[] }) {
  if (!rows.length) {
    return <div className="empty">No category rows.</div>;
  }
  const max = Math.max(1, ...rows.map((row) => Math.abs(Number(row.net_pnl ?? 0))));
  return (
    <div className="bars">
      {rows.map((row) => {
        const width = Math.max(4, Math.round((Math.abs(Number(row.net_pnl ?? 0)) / max) * 100));
        return (
          <div className="bar-row" key={row.category}>
            <span>{row.category}</span>
            <div className="bar">
              <span style={{ width: `${width}%` }} />
            </div>
            <strong>{money(row.net_pnl)}</strong>
          </div>
        );
      })}
    </div>
  );
}
