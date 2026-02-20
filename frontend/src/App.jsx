import { useEffect, useMemo, useState } from "react";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/$/, "");
const WS_BASE =
  (import.meta.env.VITE_WS_BASE ?? "").replace(/\/$/, "") ||
  (API_BASE.startsWith("http://") || API_BASE.startsWith("https://")
    ? API_BASE.replace(/^http/, "ws")
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${API_BASE}`);

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

const beijingFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false
});

const formatDate = (value) => {
  if (!value) return "--";
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)) {
    return text;
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  const parts = beijingFormatter.formatToParts(parsed);
  const pick = (type) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")} ${pick("hour")}:${pick(
    "minute"
  )}:${pick("second")}`;
};

const buildIdempotencyKey = () => {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

function App() {
  const [pnlSummary, setPnlSummary] = useState(null);
  const [accountSummary, setAccountSummary] = useState(null);
  const [positions, setPositions] = useState([]);
  const [historyPositions, setHistoryPositions] = useState([]);
  const [totalTrendSeries, setTotalTrendSeries] = useState([]);
  const [wsStatus, setWsStatus] = useState("disconnected");
  const [ibStatus, setIbStatus] = useState({
    connected: false,
    ibkr_connected: false,
    error: null,
    last_update: null,
    last_connected_at: null
  });
  const [expanded, setExpanded] = useState(new Set());
  const [tradesByPosition, setTradesByPosition] = useState({});
  const [activeView, setActiveView] = useState("current");
  const [hoveredTrendPoint, setHoveredTrendPoint] = useState(null);
  const [orderForm, setOrderForm] = useState({
    symbol: "",
    qty: 1,
    side: "buy",
    order_type: "MKT",
    price: ""
  });
  const [orderStatus, setOrderStatus] = useState(null);

  const baseCurrency = pnlSummary?.base_currency ?? "USD";
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
      pnlSummaryRes,
      positionsRes,
      historyRes,
      accountSummaryRes,
      totalTrendRes
    ] =
        await Promise.all([
          fetch(`${API_BASE}/pnl/summary`),
          fetch(`${API_BASE}/positions`),
          fetch(`${API_BASE}/positions/history`),
          fetch(`${API_BASE}/account/summary`),
          fetch(`${API_BASE}/pnl/total-trend`)
        ]);
    setPnlSummary(await pnlSummaryRes.json());
    setPositions(await positionsRes.json());
    setHistoryPositions(await historyRes.json());
    setAccountSummary(await accountSummaryRes.json());
    setTotalTrendSeries(await totalTrendRes.json());
  };

    fetchSnapshot().catch(() => setWsStatus("error"));
  }, []);

  useEffect(() => {
    let active = true;
    const fetchTotalTrendSeries = async () => {
      try {
        const response = await fetch(`${API_BASE}/pnl/total-trend`);
        const payload = await response.json();
        if (active) {
          setTotalTrendSeries(payload);
        }
      } catch (error) {
        if (active) {
          setTotalTrendSeries([]);
        }
      }
    };

    fetchTotalTrendSeries();
    const interval = setInterval(fetchTotalTrendSeries, 15000);

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
            ibkr_connected: false,
            error: "IB status unavailable"
          }));
        }
      }
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 2000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const socket = new WebSocket(`${WS_BASE}/ws/updates`);

    socket.addEventListener("open", () => setWsStatus("live"));
    socket.addEventListener("close", () => setWsStatus("disconnected"));
    socket.addEventListener("error", () => setWsStatus("error"));
    socket.addEventListener("message", (event) => {
      const payload = JSON.parse(event.data);
      setPnlSummary(payload.pnl_summary);
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

    positions.forEach((pos) => {
      if (pos?.id && !tradesByPosition[pos.id]) {
        fetchTrades(pos.id).catch(() => null);
      }
    });

    expanded.forEach((positionId) => {
      if (!tradesByPosition[positionId]) {
        fetchTrades(positionId).catch(() => null);
      }
    });
  }, [expanded, positions, tradesByPosition]);

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

  const gatewayConnected = ibStatus.connected;
  const ibkrConnected = ibStatus.ibkr_connected === true;
  const gatewayStatusClass = gatewayConnected
    ? "live"
    : ibStatus.error
    ? "error"
    : "disconnected";
  const ibkrStatusClass = ibkrConnected ? "live" : "error";

  const accountTotalPnl = pnlSummary?.total_pnl ?? null;
  const sortedPositions = useMemo(() => {
    const copy = [...positions];
    copy.sort((a, b) => {
      const valueA = Math.abs(Number(a.qty || 0) * Number(a.avg_cost || 0));
      const valueB = Math.abs(Number(b.qty || 0) * Number(b.avg_cost || 0));
      return valueB - valueA;
    });
    return copy;
  }, [positions]);

  const totalTrendChart = useMemo(() => {
    if (!totalTrendSeries || totalTrendSeries.length === 0) {
      return null;
    }
    const width = 640;
    const height = 220;
    const padding = {
      top: 22,
      right: 24,
      bottom: 28,
      left: 72
    };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    const values = totalTrendSeries.map(
      (item) => item.total_pnl ?? 0
    );
    const allValues = [...values, 0];
    const minValue = Math.min(...allValues);
    const maxValue = Math.max(...allValues);
    const range = maxValue - minValue || 1;
    const stepX =
      totalTrendSeries.length > 1
        ? chartWidth / (totalTrendSeries.length - 1)
        : 0;
    const toPoint = (value, index) => {
      const x = padding.left + index * stepX;
      const y =
        height -
        padding.bottom -
        ((value - minValue) / range) * chartHeight;
      return { x, y };
    };
    const valuePoints = values.map((value, index) => {
      const point = toPoint(value, index);
      return {
        ...point,
        value,
        index,
        date: totalTrendSeries[index]?.trade_date ?? "--"
      };
    });
    const points = valuePoints.map((point) => `${point.x},${point.y}`).join(" ");
    const ticks = [maxValue, (minValue + maxValue) / 2, minValue].map(
      (value) => ({
        value,
        y:
          height -
          padding.bottom -
          ((value - minValue) / range) * chartHeight
      })
    );
    const labels = {
      start: totalTrendSeries[0]?.trade_date,
      mid:
        totalTrendSeries[Math.floor((totalTrendSeries.length - 1) / 2)]
          ?.trade_date ?? totalTrendSeries[0]?.trade_date,
      end: totalTrendSeries[totalTrendSeries.length - 1]?.trade_date
    };
    return {
      width,
      height,
      minValue,
      maxValue,
      padding,
      points,
      valuePoints,
      ticks,
      labels
    };
  }, [totalTrendSeries]);

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

  const renderCurrentRow = (pos) => {
    const costBasis = Math.abs((pos.qty ?? 0) * (pos.avg_cost ?? 0));
    const unrealizedRatio =
      costBasis > 0 ? pos.unrealized_pnl / costBasis : null;
    const totalRatio = costBasis > 0 ? pos.total_pnl / costBasis : null;
    const positionValue = (pos.qty ?? 0) * (pos.avg_cost ?? 0);
    const trades = tradesByPosition[pos.id];
    const commissionTotal = trades
      ? trades.reduce((sum, trade) => sum + Number(trade.commission || 0), 0)
      : null;

    return (
      <div className="position-block" key={`${pos.id}-current`}>
        <div className="row current">
          <span className="symbol">{pos.symbol}</span>
          <span className="time">
            <div>{formatDate(pos.open_time)}</div>
          </span>
          <span>{numberFormatter.format(pos.qty)}</span>
          <span>{money.format(pos.avg_cost)}</span>
          <span>{money.format(positionValue)}</span>
          <span className={pos.daily_pnl >= 0 ? "pos" : "neg"}>
            {money.format(pos.daily_pnl)}
          </span>
          <span className={pos.realized_pnl >= 0 ? "pos" : "neg"}>
            {money.format(pos.realized_pnl)}
          </span>
          <div className={`cell-stack ${pos.unrealized_pnl >= 0 ? "pos" : "neg"}`}>
            <span>{money.format(pos.unrealized_pnl)}</span>
            <span className="cell-sub">
              {unrealizedRatio == null ? "--" : percentFormatter.format(unrealizedRatio)}
            </span>
          </div>
          <span>{commissionTotal == null ? "--" : money.format(commissionTotal)}</span>
          <div className={`cell-stack ${pos.total_pnl >= 0 ? "pos" : "neg"}`}>
            <span>{money.format(pos.total_pnl)}</span>
            <span className="cell-sub">
              {totalRatio == null ? "--" : percentFormatter.format(totalRatio)}
            </span>
          </div>
          <button
            className="toggle"
            onClick={() => toggleExpanded(pos.id)}
            aria-label={expanded.has(pos.id) ? "Collapse trades" : "Expand trades"}
          >
            {expanded.has(pos.id) ? "-" : "+"}
          </button>
        </div>
        {expanded.has(pos.id) && (
          <div className="trade-panel">{renderTrades(pos.id)}</div>
        )}
      </div>
    );
  };

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
        <button
          className="toggle"
          onClick={() => toggleExpanded(pos.id)}
          aria-label={expanded.has(pos.id) ? "Collapse trades" : "Expand trades"}
        >
          {expanded.has(pos.id) ? "-" : "+"}
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
                <span className={`status ${gatewayStatusClass}`}>
                  {gatewayConnected ? "Gateway Connected" : "Gateway Disconnected"}
                </span>
                <span className={`status ${ibkrStatusClass}`}>
                  {ibkrConnected ? "IBKR Connected" : "IBKR Disconnected"}
                </span>
                {ibStatus.error && (
                  <span className="status-note">{ibStatus.error}</span>
                )}
              </div>
            </div>
          </div>
          <div className="summary">
            <div
              className={`summary-card ${
                pnlSummary?.daily_pnl != null
                  ? pnlSummary.daily_pnl >= 0
                    ? "summary-pos"
                    : "summary-neg"
                  : "summary-pos"
              }`}
            >
              <p>Daily PnL</p>
              <strong
                className={
                  pnlSummary?.daily_pnl != null
                    ? pnlSummary.daily_pnl >= 0
                      ? "pos"
                      : "neg"
                    : ""
                }
              >
                {pnlSummary?.daily_pnl != null ? money.format(pnlSummary.daily_pnl) : "--"}
              </strong>
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
            </div>
          </div>
        </header>

        <section className="panel-grid">
          <div className="panel">
            <div className="panel-header">
              <h2>Total PnL (Trend)</h2>
              <span className="tag">Account</span>
            </div>
            {totalTrendChart ? (
              <div className="chart">
                <div className="chart-canvas">
                  <svg
                    className="pnl-chart"
                    viewBox={`0 0 ${totalTrendChart.width} ${totalTrendChart.height}`}
                    role="img"
                    aria-label="Total PnL trend curve"
                  >
                    <defs>
                      <linearGradient id="tradeLine" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="#2a6f7d" />
                        <stop offset="100%" stopColor="#6bb49c" />
                      </linearGradient>
                    </defs>
                    <line
                      className="chart-axis"
                      x1={totalTrendChart.padding.left}
                      y1={totalTrendChart.padding.top}
                      x2={totalTrendChart.padding.left}
                      y2={totalTrendChart.height - totalTrendChart.padding.bottom}
                    />
                    {totalTrendChart.ticks.map((tick, index) => (
                      <g key={`tick-${index}`}>
                        <line
                          className="chart-grid"
                          x1={totalTrendChart.padding.left}
                          y1={tick.y}
                          x2={
                            totalTrendChart.width -
                            totalTrendChart.padding.right
                          }
                          y2={tick.y}
                        />
                        <text
                          className="chart-axis-label"
                          x={totalTrendChart.padding.left - 8}
                          y={tick.y + 4}
                          textAnchor="end"
                        >
                          {money.format(tick.value)}
                        </text>
                      </g>
                    ))}
                    <polyline
                      className="pnl-line cumulative"
                      points={totalTrendChart.points}
                      fill="none"
                      stroke="url(#tradeLine)"
                      strokeWidth="3"
                    />
                    {totalTrendChart.valuePoints.map((point) => (
                      <circle
                        key={`point-${point.index}`}
                        className="pnl-point"
                        cx={point.x}
                        cy={point.y}
                        r="4"
                        onMouseEnter={() => setHoveredTrendPoint(point)}
                        onMouseLeave={() => setHoveredTrendPoint(null)}
                      />
                    ))}
                  </svg>
                  {hoveredTrendPoint && (
                    <div
                      className="chart-tooltip"
                      style={{
                        left: `${hoveredTrendPoint.x + 12}px`,
                        top: `${hoveredTrendPoint.y - 12}px`
                      }}
                    >
                      <div className="chart-tooltip-date">
                        {hoveredTrendPoint.date}
                      </div>
                      <strong>{money.format(hoveredTrendPoint.value)}</strong>
                    </div>
                  )}
                </div>
                <div className="chart-labels">
                  <span>{totalTrendChart.labels.start ?? "--"}</span>
                  <span>{totalTrendChart.labels.mid ?? "--"}</span>
                  <span>{totalTrendChart.labels.end ?? "--"}</span>
                </div>
              </div>
            ) : (
              <div className="row empty">No total PnL yet.</div>
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
                <span>Time</span>
                <span>Qty</span>
                <span>Avg Cost</span>
                <span>Value</span>
                <span>Daily</span>
                <span>Realized</span>
                <span>Unrealized</span>
                <span>FEE</span>
                <span>Total</span>
                <span></span>
              </div>
              {positions.length === 0 && (
                <div className="row empty">No positions yet.</div>
              )}
              {sortedPositions.map((pos) => renderCurrentRow(pos))}
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
