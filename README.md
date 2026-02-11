# IBKR PnL Tracker

Local, real-time portfolio PnL tracking for IBKR using IBKR-pushed positions, executions, commissions, and unrealized PnL.

## Features
- Live positions and PnL (realized, unrealized, total) from IBKR events
- IBKR Gateway integration via `ib_insync`
- PostgreSQL storage for trades and position snapshots
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

Note: `IBKR_DATABASE_URL` (PostgreSQL) must be set before starting the API.

### IBKR Environment Variables

- `IBKR_DATABASE_URL` (required, PostgreSQL connection string)
- `IBKR_HOST` (default `127.0.0.1`)
- `IBKR_PORT` (default `7497`)
- `IBKR_CLIENT_ID` (default `1`)
- `IBKR_ORDER_CLIENT_ID` (default `IBKR_CLIENT_ID + 1`)
- `IBKR_BASE_CURRENCY` (default `USD`)
- `IBKR_READONLY` (default `true`)
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

## 本地/局域网部署（单机）

默认假设：前端、后端、IB Gateway/TWS 部署在同一台机器。

### 1) IB Gateway / TWS 设置
1. 启用 API：`Enable ActiveX and Socket Clients`
1. Trusted IPs 填 `127.0.0.1`
1. 端口使用默认 `4001`（IB Gateway）或 `7497`（TWS）

### 1.1) IB Gateway 部署方式（本地/单机）
推荐直接安装并运行 **IB Gateway** 客户端（更稳定、更省资源）。

如需 Docker 方式，可用仓库里的镜像构建：
```powershell
cd ib-gateway
docker build --platform=linux/amd64 -t ib-gateway:local .
docker network create ibkr-net
docker run -d --name ib-gateway --network ibkr-net -p 4001:4001 -p 5900:5900 -p 6080:6080 ib-gateway:local
```
说明：端口 `4001` 为 IB Gateway API，`5900/6080` 用于 VNC/网页版登录和 2FA。  
更多细节见 `ib-gateway/README.md`。

### 2) PostgreSQL（本地）
```powershell
docker run -d --name ibkr-postgres --network ibkr-net `
  -e POSTGRES_USER=ibkr -e POSTGRES_PASSWORD=ibkr -e POSTGRES_DB=ibkr `
  -p 5432:5432 postgres:16
```
本地连接字符串示例：`postgresql://ibkr:ibkr@127.0.0.1:5432/ibkr`

### 3) 后端（Docker）
```powershell
cd backend
# docker build -t ibkr-backend:local \
#  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
#  .
docker build -t ibkr-backend:local .

# %2F 是 '/' 的 URL 编码
docker run -d --name ibkr-backend \
  --network ibkr-net \
  --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://weizhi:q7410%2F8520@ib-pg.postgres.database.azure.com:5432/ib \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```
如果你使用 TWS 而不是 IB Gateway，把 `IBKR_PORT` 改成 `7497`。

#### 容器互联注意
如果 **IB Gateway 在容器里**，后端容器不能用 `127.0.0.1` 连接它。推荐两种方式：

- **Windows / macOS**：后端用 `IBKR_HOST=host.docker.internal`
- **Linux / 任意平台**：创建自定义网络，后端用容器名连接

示例（同一 Docker 网络）：
```powershell
docker network create ibkr-net
docker run -d --name ib-gateway --network ibkr-net -p 4001:4001 -p 5900:5900 -p 6080:6080 ib-gateway:local
docker run -d --name ibkr-postgres --network ibkr-net `
  -e POSTGRES_USER=ibkr -e POSTGRES_PASSWORD=ibkr -e POSTGRES_DB=ibkr `
  -p 5432:5432 postgres:16
docker run -d --name ibkr-backend --network ibkr-net -p 8000:8000 `
  -e IBKR_DATABASE_URL=postgresql://ibkr:ibkr@ibkr-postgres:5432/ibkr `
  -e IBKR_HOST=ib-gateway -e IBKR_PORT=4001 -e IBKR_READONLY=false `
  ibkr-backend:local
```

### 4) 前端（Docker）
本地访问：
```powershell
cd frontend
docker build -t ibkr-frontend:local --build-arg VITE_API_BASE=http://127.0.0.1:8000 .
docker run -d --name ibkr-frontend -p 8080:80 ibkr-frontend:local
```

局域网访问：
```powershell
cd frontend
docker build -t ibkr-frontend:lan --build-arg VITE_API_BASE=http://192.168.50.119:8000 .
docker run -d --name ibkr-frontend -p 80:80 ibkr-frontend:lan
```

局域网其它设备访问：`http://<服务器内网IP>`

## Notes
- The system surfaces IBKR-provided realized PnL per execution (commission report event) and sums it per position.
- Unrealized PnL is taken from IBKR `reqPnLSingle` updates.

## TODO
- Review database backup/restore strategy for cloud PostgreSQL.

## Kubernetes
See `ibkr-pnl-tracker/k8s/README.txt` for AKS-ready manifests (frontend, backend, IB Gateway, VNC, RBAC).

## IB Gateway Image
Self-build Dockerfile is available at `ibkr-pnl-tracker/ib-gateway/Dockerfile`. See `ibkr-pnl-tracker/ib-gateway/README.md` for build/run instructions.





要加这两个规则，否额则无法访问 IBKR 的域名，导致无法连接 IB Gateway API。
- DOMAIN-SUFFIX,ibllc.com, 🎯 全球直连
- DOMAIN-SUFFIX,ibkr.com, 🎯 全球直连