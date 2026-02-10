# IBKR PnL Tracker

Local, real-time portfolio PnL tracking for IBKR using IBKR-pushed positions, executions, commissions, and unrealized PnL.

## Features
- Live positions and PnL (realized, unrealized, total) from IBKR events
- IBKR Gateway integration via `ib_insync`
- SQLite storage for trades and position snapshots
- React dashboard with WebSocket updates

## Backend Setup

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the API:

```bash
uvicorn app.main:app --reload
```

### IBKR Environment Variables

- `IBKR_HOST` (default `127.0.0.1`)
- `IBKR_PORT` (default `7497`)
- `IBKR_CLIENT_ID` (default `1`)
- `IBKR_ORDER_CLIENT_ID` (default `IBKR_CLIENT_ID + 1`)
- `IBKR_BASE_CURRENCY` (default `USD`)
- `IBKR_READONLY` (default `true`)
- `IBKR_DB_PATH` (default `backend/data/ibkr.db`)
- `IBKR_AUTO_SYNC` (default `true`)
- `IBKR_RECONNECT_MIN_DELAY` (default `3` seconds)
- `IBKR_RECONNECT_MAX_DELAY` (default `60` seconds)
- `IBKR_KEEPALIVE_SECONDS` (default `15` seconds)
- `IBKR_GATEWAY_RESTART_ENABLED` (default `false`)
- `IBKR_GATEWAY_DEPLOYMENT` (default `ib-gateway`)
- `IBKR_GATEWAY_NAMESPACE` (default `default`)
- `IBKR_GATEWAY_VNC_URL` (default empty)

Sync health:

```bash
curl http://localhost:8000/sync/health
```

Restart IB Gateway (requires k8s RBAC + env config):

```bash
curl -X POST http://localhost:8000/gateway/restart
```

Place order (market or limit):

```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","qty":1,"side":"buy","order_type":"MKT"}'
```

### Recommended IBKR User Setup (Avoid Disconnects)

IBKR treats a single username session as mutually exclusive. Logging into IBKR Portal or the mobile app with the same user can force IB Gateway to disconnect. To keep the gateway connected while you trade elsewhere:

- Create a **Secondary User** dedicated to IB Gateway.
- Grant **API access + account data** but **no trading permission** (read-only).
- Use this secondary user for IB Gateway, and your main user for web/mobile trading.

This prevents your web/mobile sessions from kicking the gateway offline.

### IB Gateway Data Flow

Passive events (IB Gateway push to backend):
- `positionEvent`: current positions (symbol, qty, avgCost) -> `positions`
- `execDetailsEvent`: trade executions (time, price, qty, side) -> `trades`
- `commissionReportEvent`: commission/realized PnL by execId -> `trades.commission` + `trades.realized_pnl`
- `pnlSingleEvent` (from `reqPnLSingle`): unrealized PnL -> `positions.unrealized_pnl`

Active requests (backend pull from IB Gateway):
- `reqPositions()`: positions snapshot on connect -> `positions`
- `reqExecutions()`: executions backfill on connect -> `trades`
- `reqPnLSingle()`: unrealized PnL by position -> `positions.unrealized_pnl`
- `reqCurrentTime()`: keepalive heartbeat

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Set API base if needed:

```bash
VITE_API_BASE=http://localhost:8000
```

## Notes
- The system surfaces IBKR-provided realized PnL per execution (commission report event) and sums it per position.
- Unrealized PnL is taken from IBKR `reqPnLSingle` updates.

## TODO
- Replace SQLite with a managed database for cross-cluster persistence.

## Kubernetes
See `ibkr-pnl-tracker/k8s/README.txt` for AKS-ready manifests (frontend, backend, IB Gateway, VNC, RBAC).

## IB Gateway Image
Self-build Dockerfile is available at `ibkr-pnl-tracker/ib-gateway/Dockerfile`. See `ibkr-pnl-tracker/ib-gateway/README.md` for build/run instructions.
