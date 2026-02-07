# IBKR PnL Tracker

Local, real-time portfolio PnL tracking for IBKR using average cost basis. Combines realized and unrealized PnL, includes fees and FX conversion.

## Features
- Live positions and PnL (realized, unrealized, total)
- IBKR Gateway integration via `ib_insync`
- SQLite storage for trades, positions, prices, and FX rates
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
- `IBKR_BASE_CURRENCY` (default `USD`)
- `IBKR_READONLY` (default `true`)
- `IBKR_DB_PATH` (default `backend/data/ibkr.db`)
- `IBKR_AUTO_SYNC` (default `true`)
- `IBKR_RECONNECT_MIN_DELAY` (default `3` seconds)
- `IBKR_RECONNECT_MAX_DELAY` (default `60` seconds)
- `IBKR_KEEPALIVE_SECONDS` (default `30` seconds)
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
- The system computes realized PnL from trade history it receives. If you start after existing positions are open, the realized PnL before startup will not be included unless you backfill executions.
- Average cost basis is used, not FIFO.
- FX conversion uses live rates when available; missing FX defaults to 1.0.

## TODO
- Replace SQLite with a managed database for cross-cluster persistence.

## Kubernetes
See `ibkr-pnl-tracker/k8s/README.txt` for AKS-ready manifests (frontend, backend, IB Gateway, VNC, RBAC).

## IB Gateway Image
Self-build Dockerfile is available at `ibkr-pnl-tracker/ib-gateway/Dockerfile`. See `ibkr-pnl-tracker/ib-gateway/README.md` for build/run instructions.
