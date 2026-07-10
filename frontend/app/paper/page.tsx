import { PaperRunButton } from "@/components/PaperRunButton";
import { decimal, getJson, isoDate, money, pct, shortId } from "@/lib/api";

type Row = Record<string, any>;

type SummaryResponse = {
  strategy_version: string;
  sampling_note: string;
  summary: {
    strategy: Row;
    order_status_distribution: Record<string, number>;
    reject_distribution: Record<string, number>;
    runtime: Row;
  };
};

type SignalsResponse = { signals: Row[]; pagination: { total: number } };
type OrdersResponse = { orders: Row[]; pagination: { total: number } };

export default async function PaperTradingPage() {
  const [summaryResult, signalsResult, ordersResult] = await Promise.all([
    getJson<SummaryResponse>("/paper/summary"),
    getJson<SignalsResponse>("/paper/signals?limit=100"),
    getJson<OrdersResponse>("/paper/orders?limit=100"),
  ]);
  const summary = summaryResult.data?.summary;
  const strategy = summary?.strategy ?? {};
  const runtime = summary?.runtime ?? {};
  const signals = signalsResult.data?.signals ?? [];
  const orders = ordersResult.data?.orders ?? [];
  const statuses = summary?.order_status_distribution ?? {};
  const rejects = summary?.reject_distribution ?? {};

  return (
    <main className="shell">
      <section className="detail-title">
        <div>
          <div className="eyebrow">Week08 · simulation only</div>
          <h1>Paper copy-trading evidence</h1>
          <p className="alert-message">
            No private keys, credentials, or real orders. Fills are estimated from archived orderbook depth.
          </p>
        </div>
        <PaperRunButton />
      </section>

      <section className="metric-grid">
        <Metric label="Signals" value={signalsResult.data?.pagination.total ?? 0} note={`${signals.length} loaded`} />
        <Metric label="Paper orders" value={ordersResult.data?.pagination.total ?? 0} note={`${statuses.rejected ?? 0} rejected`} />
        <Metric label="Net PnL" value={money(strategy.net_pnl)} note={`ROI ${pct(strategy.net_roi)}`} />
        <Metric label="Win rate" value={pct(strategy.win_rate)} note={`max DD ${money(strategy.max_drawdown)}`} />
      </section>

      <section className="two-col" style={{ marginTop: 18 }}>
        <div className="section">
          <div className="section-header">
            <div><div className="eyebrow">Lifecycle</div><h2>Order status</h2></div>
            <span className="pill">{summaryResult.data?.strategy_version ?? "weighted_copy_v1"}</span>
          </div>
          <Distribution rows={statuses} empty="No paper orders yet." />
        </div>
        <div className="section">
          <div className="section-header">
            <div><div className="eyebrow">Risk evidence</div><h2>Rejected signal reasons</h2></div>
            <span className="pill warn">explicit gates</span>
          </div>
          <Distribution rows={rejects} empty="No rejected signals yet." />
        </div>
      </section>

      <section className="section" style={{ marginTop: 18 }}>
        <div className="section-header">
          <div><div className="eyebrow">Simulation</div><h2>Latest paper orders</h2></div>
          <span className="pill">USDC</span>
        </div>
        {ordersResult.error ? <div className="error">{ordersResult.error}</div> : null}
        {orders.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Order</th><th>Side / type</th><th>Status</th><th>Requested</th><th>Fill</th><th>Slippage</th><th>Fee</th><th>Net PnL</th><th>Latency</th><th>Reason</th></tr></thead>
            <tbody>{orders.map((order) => (
              <tr key={order.order_id}>
                <td>{shortId(order.order_id, 8, 4)}</td><td>{order.side} · {order.order_type}</td>
                <td><span className={`pill ${order.status === "rejected" ? "bad" : "good"}`}>{order.status}</span></td>
                <td>{money(order.requested_notional)}</td><td>{decimal(order.filled_size, 2)} @ {decimal(order.estimated_fill_price, 4)}</td>
                <td>{decimal(order.estimated_slippage, 4)}</td><td>{money(order.estimated_fee)}</td><td>{money(order.net_pnl)}</td>
                <td>{order.detection_latency_ms ?? 0}/{order.decision_latency_ms ?? 0}/{order.simulation_latency_ms ?? 0} ms</td>
                <td>{order.reject_reason ?? "—"}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <div className="empty">Run a paper cycle after fresh wallet trades and orderbooks are available.</div>}
      </section>

      <section className="section" style={{ marginTop: 18 }}>
        <div className="section-header">
          <div><div className="eyebrow">Traceability</div><h2>Latest signals</h2></div>
          <span className="pill">{isoDate(runtime.last_run_at)}</span>
        </div>
        {signalsResult.error ? <div className="error">{signalsResult.error}</div> : null}
        {signals.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Detected</th><th>Leader</th><th>Market / token</th><th>Side</th><th>Leader fill</th><th>Weight</th><th>Reason</th><th>Processing</th></tr></thead>
            <tbody>{signals.map((row) => (
              <tr key={row.signal_id}><td>{isoDate(row.detected_at)}</td><td>{shortId(row.leader_wallet)}</td>
                <td>{shortId(row.market_id, 8, 4)} / {shortId(row.token_id, 8, 4)}</td><td>{row.side}</td>
                <td>{decimal(row.leader_size, 2)} @ {decimal(row.leader_price, 4)}</td><td>{decimal(row.wallet_weight, 3)}</td>
                <td>{row.reason}</td><td>{row.order_status ?? row.processing_status}</td></tr>
            ))}</tbody>
          </table></div>
        ) : <div className="empty">No eligible high-score or watchlist-wallet trades in the scanned window.</div>}
      </section>

      <div className="empty" style={{ marginTop: 18 }}>
        {summaryResult.data?.sampling_note ?? "Seven-day stability and 100-order thresholds are pending ongoing sampling."}
      </div>
    </main>
  );
}

function Metric({ label, value, note }: { label: string; value: string | number; note: string }) {
  return <div className="metric"><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-note">{note}</div></div>;
}

function Distribution({ rows, empty }: { rows: Record<string, number>; empty: string }) {
  const entries = Object.entries(rows);
  if (!entries.length) return <div className="empty">{empty}</div>;
  return <div className="bars">{entries.map(([name, count]) => <div className="bar-row" key={name}><span>{name}</span><div className="bar"><span style={{ width: `${Math.max(6, Math.min(100, count * 8))}%` }} /></div><strong>{count}</strong></div>)}</div>;
}
