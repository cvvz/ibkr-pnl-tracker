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

const percentFormatter = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 1
});

const formatDate = (value) => {
  if (!value) return "--";
  return value.split("T")[0] ?? value;
};

const buildIdempotencyKey = () => {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

function App() {
  const [summary, setSummary] = useState(null);
  const [accountSummary, setAccountSummary] = useState(null);
  const [positions, setPositions] = useState([]);
  const [historyPositions, setHistoryPositions] = useState([]);
  const [dailyPnlTrendSeries, setDailyPnlTrendSeries] = useState([]);
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
  const [orderForm, setOrderForm] = useState({
    symbol: "",
    qty: 1,
    side: "buy",
    order_type: "MKT",
    price: ""
  });
  const [orderStatus, setOrderStatus] = useState(null);

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
    const [
      summaryRes,
      positionsRes,
      historyRes,
      accountSummaryRes,
      dailyPnlTrendRes
    ] =
        await Promise.all([
          fetch(`${API_BASE}/pnl/summary`),
          fetch(`${API_BASE}/positions`),
          fetch(`${API_BASE}/positions/history`),
          fetch(`${API_BASE}/account/summary`),
          fetch(`${API_BASE}/pnl/trade-cumulative`)
        ]);
    setSummary(await summaryRes.json());
    setPositions(await positionsRes.json());
    setHistoryPositions(await historyRes.json());
    setAccountSummary(await accountSummaryRes.json());
    setDailyPnlTrendSeries(await dailyPnlTrendRes.json());
  };

    fetchSnapshot().catch(() => setWsStatus("error"));
  }, []);

  useEffect(() => {
    let active = true;
    const fetchDailyPnlTrendSeries = async () => {
      try {
        const response = await fetch(`${API_BASE}/pnl/trade-cumulative`);
        const payload = await response.json();
        if (active) {
          setDailyPnlTrendSeries(payload);
        }
      } catch (error) {
        if (active) {
          setDailyPnlTrendSeries([]);
        }
      }
    };

    fetchDailyPnlTrendSeries();
    const interval = setInterval(fetchDailyPnlTrendSeries, 15000);

    return () => {
      active = false;
      clearInterval(interval);
    };
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
      if (payload.account_summary) {
        setAccountSummary(payload.account_summary);
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

  const restartGateway = async () => {
    await fetch(`${API_BASE}/gateway/restart`, { method: "POST" });
    if (ibStatus.vnc_url) {
      window.open(ibStatus.vnc_url, "_blank");
    }
  };

  const submitOrder = async (event) => {
    event.preventDefault();
    setOrderStatus({ state: "pending", message: "Placing order..." });
    try {
      const idempotencyKey = buildIdempotencyKey();
      const payload = {
        symbol: orderForm.symbol.trim(),
        qty: Number(orderForm.qty),
        side: orderForm.side,
        order_type: orderForm.order_type
      };
      if (orderForm.order_type === "LMT") {
        payload.price = Number(orderForm.price);
      }
      const response = await fetch(`${API_BASE}/orders`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey
        },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        throw new Error(errorPayload?.detail || "Order failed");
      }
      const result = await response.json();
      const message =
        result.status === "queued"
          ? "Order queued"
          : `Order ${result.order_id} ${result.status}`;
      setOrderStatus({
        state: "success",
        message
      });
    } catch (error) {
      setOrderStatus({ state: "error", message: error.message || "Order failed" });
    }
    window.setTimeout(() => setOrderStatus(null), 5000);
  };

  const ibkrStatusClass = ibStatus.connected
    ? "live"
    : ibStatus.error
    ? "error"
    : "disconnected";

  const accountTotalPnl = useMemo(() => {
    if (positions.length === 0 && historyPositions.length === 0) {
      return null;
    }
    const currentTotal = positions.reduce(
      (sum, item) => sum + (item.total_pnl ?? 0),
      0
    );
    const historyTotal = historyPositions.reduce(
      (sum, item) => sum + (item.realized_pnl ?? 0),
      0
    );
    return currentTotal + historyTotal;
  }, [positions, historyPositions]);

  const dailyPnlTrendChart = useMemo(() => {
    if (!dailyPnlTrendSeries || dailyPnlTrendSeries.length === 0) {
      return null;
    }
    const width = 640;
    const height = 220;
    const padding = 32;
    const lastIndex = dailyPnlTrendSeries.length - 1;
    const values = dailyPnlTrendSeries.map((item, index) => {
      const value = item.cumulative_pnl ?? 0;
      if (accountTotalPnl != null && index === lastIndex) {
        return accountTotalPnl;
      }
      return value;
    });
    const allValues = [...values, 0];
    const minValue = Math.min(...allValues);
    const maxValue = Math.max(...allValues);
    const range = maxValue - minValue || 1;
    const stepX =
      dailyPnlTrendSeries.length > 1
        ? (width - padding * 2) / (dailyPnlTrendSeries.length - 1)
        : 0;
    const toPoint = (value, index) => {
      const x = padding + index * stepX;
      const y =
        height -
        padding -
        ((value - minValue) / range) * (height - padding * 2);
      return `${x},${y}`;
    };
    const points = values.map(toPoint).join(" ");
    const labels = {
      start: dailyPnlTrendSeries[0]?.trade_date,
      mid:
        dailyPnlTrendSeries[Math.floor((dailyPnlTrendSeries.length - 1) / 2)]
          ?.trade_date ?? dailyPnlTrendSeries[0]?.trade_date,
      end: dailyPnlTrendSeries[dailyPnlTrendSeries.length - 1]?.trade_date
    };
    return {
      width,
      height,
      minValue,
      maxValue,
      points,
      labels
    };
  }, [dailyPnlTrendSeries, accountTotalPnl]);

  const healthMetrics = useMemo(() => {
    if (!accountSummary) {
      return [];
    }
    const netLiq = accountSummary.net_liquidation;
    const ratio = (value, denom) =>
      value == null || denom == null || denom === 0 ? null : value / denom;
    const classify = (value, direction, good, warn) => {
      if (value == null) return "neutral";
      if (direction === "low") {
        if (value <= good) return "good";
        if (value <= warn) return "warn";
        return "risk";
      }
      if (value >= good) return "good";
      if (value >= warn) return "warn";
      return "risk";
    };
    return [
      {
        key: "net",
        label: "Net Liquidation",
        value: netLiq,
        ratio: null,
        status: "neutral"
      },
      {
        key: "available",
        label: "Available Funds",
        value: accountSummary.available_funds,
        ratio: ratio(accountSummary.available_funds, netLiq),
        status: classify(ratio(accountSummary.available_funds, netLiq), "high", 0.3, 0.15)
      },
      {
        key: "excess",
        label: "Excess Liquidity",
        value: accountSummary.excess_liquidity,
        ratio: ratio(accountSummary.excess_liquidity, netLiq),
        status: classify(ratio(accountSummary.excess_liquidity, netLiq), "high", 0.25, 0.1)
      },
      {
        key: "margin",
        label: "Margin Usage",
        value: accountSummary.maint_margin_req,
        ratio: ratio(accountSummary.maint_margin_req, netLiq),
        status: classify(ratio(accountSummary.maint_margin_req, netLiq), "low", 0.35, 0.6)
      },
      {
        key: "gross",
        label: "Gross Exposure",
        value: accountSummary.gross_position_value,
        ratio: ratio(accountSummary.gross_position_value, netLiq),
        status: classify(ratio(accountSummary.gross_position_value, netLiq), "low", 1.0, 1.5)
      },
      {
        key: "short",
        label: "Short Exposure",
        value: accountSummary.short_market_value,
        ratio: ratio(accountSummary.short_market_value, netLiq),
        status: classify(ratio(accountSummary.short_market_value, netLiq), "low", 0.2, 0.35)
      }
    ];
  }, [accountSummary]);

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

  const renderCurrentRow = (pos) => (
    <div className="position-block" key={`${pos.id}-current`}>
      <div className="row current">
        <span className="symbol">{pos.symbol}</span>
        <span>{numberFormatter.format(pos.qty)}</span>
        <span>{money.format(pos.avg_cost)}</span>
        <span className={pos.realized_pnl >= 0 ? "pos" : "neg"}>
          {money.format(pos.realized_pnl)}
        </span>
        <span className={pos.unrealized_pnl >= 0 ? "pos" : "neg"}>
          {money.format(pos.unrealized_pnl)}
        </span>
        <span className={pos.daily_pnl >= 0 ? "pos" : "neg"}>
          {money.format(pos.daily_pnl)}
        </span>
        <span className={pos.total_pnl >= 0 ? "pos" : "neg"}>
          {money.format(pos.total_pnl)}
        </span>
        <span className="time">
          <div>{formatDate(pos.open_time)}</div>
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

  const renderHistoryRow = (pos) => (
    <div className="position-block" key={`${pos.id}-history`}>
      <div className="row history">
        <span className="symbol">{pos.symbol}</span>
        <span className="time">
          <div>Open: {formatDate(pos.open_time)}</div>
          <div>Close: {formatDate(pos.close_time)}</div>
        </span>
        <span className={pos.realized_pnl >= 0 ? "pos" : "neg"}>
          {money.format(pos.realized_pnl)}
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
    <div className="page">
      <div className="glow"></div>
      <main className="content">
        <header className="hero">
          <div className="hero-left">
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
          </div>
          <div className="summary">
            <div
              className={`summary-card ${
                summary?.daily_pnl != null
                  ? summary.daily_pnl >= 0
                    ? "summary-pos"
                    : "summary-neg"
                  : "summary-pos"
              }`}
            >
              <p>Daily PnL</p>
              <strong
                className={
                  summary?.daily_pnl != null
                    ? summary.daily_pnl >= 0
                      ? "pos"
                      : "neg"
                    : ""
                }
              >
                {summary?.daily_pnl != null ? money.format(summary.daily_pnl) : "--"}
              </strong>
              <div className="summary-sub">Latest daily PnL snapshot</div>
            </div>
            <div
              className={`summary-card ${
                accountTotalPnl != null
                  ? accountTotalPnl >= 0
                    ? "summary-pos"
                    : "summary-neg"
                  : "summary-pos"
              }`}
            >
              <p>Total PnL</p>
              <strong
                className={
                  accountTotalPnl != null
                    ? accountTotalPnl >= 0
                      ? "pos"
                      : "neg"
                    : ""
                }
              >
                {accountTotalPnl != null ? money.format(accountTotalPnl) : "--"}
              </strong>
              <div className="summary-sub">
                Current positions total + historical realized
              </div>
            </div>
          </div>
        </header>

        <section className="panel-grid">
          <div className="panel">
            <div className="panel-header">
              <h2>Cumulative PnL (Trend)</h2>
              <span className="tag">Trade PnL</span>
            </div>
            {dailyPnlTrendChart ? (
              <div className="chart">
                <svg
                  className="pnl-chart"
                  viewBox={`0 0 ${dailyPnlTrendChart.width} ${dailyPnlTrendChart.height}`}
                  role="img"
                  aria-label="Cumulative PnL trend curve"
                >
                  <defs>
                    <linearGradient id="tradeLine" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#2a6f7d" />
                      <stop offset="100%" stopColor="#6bb49c" />
                    </linearGradient>
                  </defs>
                  <polyline
                    className="pnl-line cumulative"
                    points={dailyPnlTrendChart.points}
                    fill="none"
                    stroke="url(#tradeLine)"
                    strokeWidth="3"
                  />
                </svg>
                <div className="chart-labels">
                  <span>{dailyPnlTrendChart.labels.start ?? "--"}</span>
                  <span>{dailyPnlTrendChart.labels.mid ?? "--"}</span>
                  <span>{dailyPnlTrendChart.labels.end ?? "--"}</span>
                </div>
              </div>
            ) : (
              <div className="row empty">No trade PnL yet.</div>
            )}
          </div>
          <div className="panel">
            <div className="panel-header">
              <h2>Account Health</h2>
              <span className="tag">Liquidity & Risk</span>
            </div>
            {healthMetrics.length === 0 ? (
              <div className="row empty">No account summary yet.</div>
            ) : (
              <>
                <div className="health-grid">
                  {healthMetrics.map((metric) => (
                    <div className={`health-card ${metric.status}`} key={metric.key}>
                      <div className="health-label">{metric.label}</div>
                      <strong>
                        {metric.value == null ? "--" : money.format(metric.value)}
                      </strong>
                      {metric.ratio != null && (
                        <span className="health-ratio">
                          {percentFormatter.format(metric.ratio)}
                        </span>
                      )}
                      {metric.ratio != null && (
                        <div className="health-bar">
                          <span
                            style={{
                              width: `${Math.min(Math.abs(metric.ratio) * 100, 100)}%`
                            }}
                          ></span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                <div className="health-meta">
                  Updated: {accountSummary?.as_of ? accountSummary.as_of : "--"}
                </div>
              </>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>Place Order</h2>
            <span className="tag">IBKR</span>
          </div>
          <form className="order-form" onSubmit={submitOrder}>
            <label>
              Symbol
              <input
                type="text"
                placeholder="AAPL"
                value={orderForm.symbol}
                onChange={(event) =>
                  setOrderForm((prev) => ({ ...prev, symbol: event.target.value }))
                }
                required
              />
            </label>
            <label>
              Side
              <select
                value={orderForm.side}
                onChange={(event) =>
                  setOrderForm((prev) => ({ ...prev, side: event.target.value }))
                }
              >
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
            </label>
            <label>
              Qty
              <input
                type="number"
                min="0.0001"
                step="0.0001"
                value={orderForm.qty}
                onChange={(event) =>
                  setOrderForm((prev) => ({ ...prev, qty: event.target.value }))
                }
                required
              />
            </label>
            <label>
              Order Type
              <select
                value={orderForm.order_type}
                onChange={(event) =>
                  setOrderForm((prev) => ({ ...prev, order_type: event.target.value }))
                }
              >
                <option value="MKT">Market</option>
                <option value="LMT">Limit</option>
              </select>
            </label>
            <label className={orderForm.order_type === "LMT" ? "" : "disabled"}>
              Limit Price
              <input
                type="number"
                min="0.0001"
                step="0.0001"
                value={orderForm.price}
                onChange={(event) =>
                  setOrderForm((prev) => ({ ...prev, price: event.target.value }))
                }
                disabled={orderForm.order_type !== "LMT"}
                required={orderForm.order_type === "LMT"}
              />
            </label>
            <button className="btn primary" type="submit">
              Submit
            </button>
            {orderStatus && (
              <span
                className={`status ${
                  orderStatus.state === "success"
                    ? "live"
                    : orderStatus.state === "pending"
                    ? "warning"
                    : "error"
                }`}
              >
                {orderStatus.message}
              </span>
            )}
          </form>
        </section>

        {activeView === "current" && (
          <section className="panel">
            <div className="panel-header">
              <h2>Current Positions</h2>
              <span className="tag">Base: {baseCurrency}</span>
            </div>
            <div className="table">
              <div className="row header current">
                <span>Symbol</span>
                <span>Qty</span>
                <span>Avg Cost</span>
                <span>Realized</span>
                <span>Unrealized</span>
                <span>Daily</span>
                <span>Total</span>
                <span>Time</span>
                <span></span>
              </div>
              {positions.length === 0 && (
                <div className="row empty">No positions yet.</div>
              )}
              {positions.map((pos) => renderCurrentRow(pos))}
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
              <div className="row header history">
                <span>Symbol</span>
                <span>Time</span>
                <span>Realized</span>
                <span></span>
              </div>
              {historyPositions.length === 0 && (
                <div className="row empty">No history yet.</div>
              )}
              {historyPositions.map((pos) => renderHistoryRow(pos))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
