import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

const currencyFormatter = (currency) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2
  });

const numberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 4
});

function App() {
  const [summary, setSummary] = useState(null);
  const [positions, setPositions] = useState([]);
  const [historyPositions, setHistoryPositions] = useState([]);
  const [wsStatus, setWsStatus] = useState("disconnected");
  const [ibStatus, setIbStatus] = useState({
    connected: false,
    error: null,
    last_update: null,
    last_connected_at: null,
    vnc_url: null
  });
  const [expanded, setExpanded] = useState(new Set());
  const [tradesByPosition, setTradesByPosition] = useState({});
  const [activeView, setActiveView] = useState("current");

  const baseCurrency = summary?.base_currency ?? "USD";
  const money = useMemo(() => currencyFormatter(baseCurrency), [baseCurrency]);

  const toggleExpanded = (positionId) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(positionId)) {
        next.delete(positionId);
      } else {
        next.add(positionId);
      }
      return next;
    });
  };

  useEffect(() => {
    const fetchSnapshot = async () => {
      const [summaryRes, positionsRes, historyRes] = await Promise.all([
        fetch(`${API_BASE}/pnl/summary`),
        fetch(`${API_BASE}/positions`),
        fetch(`${API_BASE}/positions/history`)
      ]);
      setSummary(await summaryRes.json());
      setPositions(await positionsRes.json());
      setHistoryPositions(await historyRes.json());
    };

    fetchSnapshot().catch(() => setWsStatus("error"));
  }, []);

  useEffect(() => {
    let active = true;

    const fetchHealth = async () => {
      try {
        const response = await fetch(`${API_BASE}/sync/health`);
        const payload = await response.json();
        if (active) {
          setIbStatus(payload);
        }
      } catch (error) {
        if (active) {
          setIbStatus((prev) => ({
            ...prev,
            connected: false,
            error: "IB status unavailable"
          }));
        }
      }
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 5000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const wsBase = API_BASE.replace(/^http/, "ws");
    const socket = new WebSocket(`${wsBase}/ws/updates`);

    socket.addEventListener("open", () => setWsStatus("live"));
    socket.addEventListener("close", () => setWsStatus("disconnected"));
    socket.addEventListener("error", () => setWsStatus("error"));
    socket.addEventListener("message", (event) => {
      const payload = JSON.parse(event.data);
      setSummary(payload.summary);
      setPositions(payload.positions);
      if (payload.history) {
        setHistoryPositions(payload.history);
      }
    });

    return () => socket.close();
  }, []);

  useEffect(() => {
    const fetchTrades = async (positionId) => {
      const response = await fetch(`${API_BASE}/positions/${positionId}/trades`);
      const payload = await response.json();
      setTradesByPosition((prev) => ({
        ...prev,
        [positionId]: payload
      }));
    };

    expanded.forEach((positionId) => {
      if (!tradesByPosition[positionId]) {
        fetchTrades(positionId).catch(() => null);
      }
    });
  }, [expanded, tradesByPosition]);

  const startSync = async () => {
    await fetch(`${API_BASE}/sync/start`, { method: "POST" });
  };

  const seedDemo = async () => {
    await fetch(`${API_BASE}/sync/demo`, { method: "POST" });
  };

  const restartGateway = async () => {
    await fetch(`${API_BASE}/gateway/restart`, { method: "POST" });
    if (ibStatus.vnc_url) {
      window.open(ibStatus.vnc_url, "_blank");
    }
  };

  const ibkrStatusClass = ibStatus.connected
    ? "live"
    : ibStatus.error
    ? "error"
    : "disconnected";

  const renderTrades = (positionId) => {
    const trades = tradesByPosition[positionId] || [];
    if (trades.length === 0) {
      return <div className="trade-empty">No trades yet.</div>;
    }
    return (
      <div className="trade-table">
        <div className="trade-row header">
          <span>Time</span>
          <span>Side</span>
          <span>Qty</span>
          <span>Price</span>
          <span>Fee</span>
          <span>Realized</span>
        </div>
        {trades.map((trade, index) => (
          <div className="trade-row" key={`${trade.trade_time}-${index}`}>
            <span>{trade.trade_time}</span>
            <span className={trade.side === "buy" ? "pos" : "neg"}>{trade.side}</span>
            <span>{numberFormatter.format(trade.qty)}</span>
            <span>{money.format(trade.price)}</span>
            <span>{money.format(trade.commission)}</span>
            <span className={trade.realized_pnl >= 0 ? "pos" : "neg"}>
              {money.format(trade.realized_pnl)}
            </span>
          </div>
        ))}
      </div>
    );
  };

  const renderPositionRow = (pos, isHistory) => (
    <div className="position-block" key={`${pos.id}-${isHistory ? "history" : "current"}`}>
      <div className="row">
        <span className="symbol">
          {pos.symbol}
          <small>{pos.exchange ?? ""}</small>
        </span>
        <span>{numberFormatter.format(pos.qty)}</span>
        <span>{money.format(pos.avg_cost)}</span>
        <span>{pos.market_price ? money.format(pos.market_price) : "--"}</span>
        <span className={pos.realized_pnl >= 0 ? "pos" : "neg"}>
          {money.format(pos.realized_pnl)}
        </span>
        <span className={pos.unrealized_pnl >= 0 ? "pos" : "neg"}>
          {money.format(pos.unrealized_pnl)}
        </span>
        <span className={pos.total_pnl >= 0 ? "pos" : "neg"}>
          {money.format(pos.total_pnl)}
        </span>
        <span className="time">
          <div>Open: {pos.open_time ?? "--"}</div>
          {isHistory && <div>Close: {pos.close_time ?? "--"}</div>}
        </span>
        <button className="toggle" onClick={() => toggleExpanded(pos.id)}>
          {expanded.has(pos.id) ? "Hide Trades" : "Show Trades"}
        </button>
      </div>
      {expanded.has(pos.id) && (
        <div className="trade-panel">{renderTrades(pos.id)}</div>
      )}
    </div>
  );

  return (
    <div className="page layout">
      <div className="glow"></div>
      <aside className="sidebar">
        <div className="brand">
          <span>IBKR</span>
          <strong>PnL Tracker</strong>
        </div>
        <nav className="nav">
          <button
            className={`nav-item ${activeView === "current" ? "active" : ""}`}
            onClick={() => setActiveView("current")}
          >
            Current Positions
          </button>
          <button
            className={`nav-item ${activeView === "history" ? "active" : ""}`}
            onClick={() => setActiveView("history")}
          >
            Historical Positions
          </button>
        </nav>
        <div className="side-actions">
          <button className="btn primary" onClick={startSync}>
            Start IB Sync
          </button>
          <button className="btn ghost" onClick={seedDemo}>
            Seed Demo Data
          </button>
            <div className="status-group">
              <span className={`status ${wsStatus}`}>WS {wsStatus}</span>
              <span className={`status ${ibkrStatusClass}`}>
                {ibStatus.connected ? "IB Connected" : "IB Disconnected"}
              </span>
              {!ibStatus.connected && ibStatus.vnc_url && (
                <button className="btn tiny" onClick={restartGateway}>
                  Re-auth (VNC)
                </button>
              )}
              {ibStatus.error && (
                <span className="status-note">{ibStatus.error}</span>
              )}
          </div>
        </div>
      </aside>
      <main className="content">
        <header className="hero">
          <div>
            <p className="eyebrow">IBKR Portfolio Console</p>
            <h1>
              Real-time PnL, unified.
              <span>Positions, realized, unrealized, total.</span>
            </h1>
            <p className="subtitle">
              Average cost basis with fee-aware accounting. Live prices and FX
              conversion keep the view aligned with what you can liquidate today.
            </p>
          </div>
          <div className="summary">
            <div className="summary-card">
              <p>Realized</p>
              <strong>
                {summary ? money.format(summary.realized_pnl) : "--"}
              </strong>
            </div>
            <div className="summary-card">
              <p>Unrealized</p>
              <strong>
                {summary ? money.format(summary.unrealized_pnl) : "--"}
              </strong>
            </div>
            <div className="summary-card accent">
              <p>Total</p>
              <strong>{summary ? money.format(summary.total_pnl) : "--"}</strong>
            </div>
          </div>
        </header>

        {activeView === "current" && (
          <section className="panel">
            <div className="panel-header">
              <h2>Current Positions</h2>
              <span className="tag">Base: {baseCurrency}</span>
            </div>
            <div className="table">
              <div className="row header">
                <span>Symbol</span>
                <span>Qty</span>
                <span>Avg Cost</span>
                <span>Market</span>
                <span>Realized</span>
                <span>Unrealized</span>
                <span>Total</span>
                <span>Time</span>
                <span></span>
              </div>
              {positions.length === 0 && (
                <div className="row empty">No positions yet.</div>
              )}
              {positions.map((pos) => renderPositionRow(pos, false))}
            </div>
          </section>
        )}

        {activeView === "history" && (
          <section className="panel">
            <div className="panel-header">
              <h2>Historical Positions</h2>
              <span className="tag">Closed</span>
            </div>
            <div className="table">
              <div className="row header">
                <span>Symbol</span>
                <span>Qty</span>
                <span>Avg Cost</span>
                <span>Market</span>
                <span>Realized</span>
                <span>Unrealized</span>
                <span>Total</span>
                <span>Time</span>
                <span></span>
              </div>
              {historyPositions.length === 0 && (
                <div className="row empty">No history yet.</div>
              )}
              {historyPositions.map((pos) => renderPositionRow(pos, true))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
