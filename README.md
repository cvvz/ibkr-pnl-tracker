# IBKR PnL Tracker

[English](#english) | [中文](#中文)

## English

IBKR PnL Tracker is a real-time trading PnL dashboard for Interactive Brokers. It connects to IB Gateway, caches live data in memory, and periodically persists only the necessary updates to the database to reduce write pressure. The frontend consumes WebSocket updates for live views and REST APIs for snapshots.

![Dashboard Overview](./image.png)

**Key Features**
- Real-time positions, historical positions, daily PnL, and total PnL with live WebSocket updates.
- Total PnL trend chart with hover tooltips.
- Account health metrics (net liquidation, available funds, margin requirements).
- Gateway status and IBKR server connectivity status.
- Order placement panel (market/limit) with order status feedback.
- Trade drill-down per position, including fee totals (computed client-side).

**Data Flow**
- IB Gateway pushes positions, PnL, and account summaries to the backend.
- Backend maintains an in-memory cache for fast reads and reduces database writes.
- Frontend reads from WebSocket for real-time views and REST endpoints for snapshots.

**Use Cases**
- Monitor current positions and PnL in one place.
- Track daily performance trends across sessions.
- Check account liquidity and margin health at a glance.

**Current Positions Fields**
- `Symbol`: Ticker symbol.
- `Time`: Position open time (Beijing time).
- `Qty`: Position size.
- `Avg Cost`: Average entry cost.
- `Value`: `Qty * Avg Cost` (not stored in DB).
- `Daily`: Daily PnL for this position.
- `Realized`: Realized PnL for this position.
- `Unrealized`: Unrealized PnL; the percent below is `Unrealized / |Qty * Avg Cost|`.
- `FEE`: Sum of commissions for trades under this position (computed client-side).
- `Total`: Total PnL; the percent below is `Total / |Qty * Avg Cost|`.

**Historical Positions**
Closed positions are listed in `Historical Positions`, showing open/close time and realized PnL. You can expand a row to see the trade list for that position.

**Quick Start (Single Host, Docker)**
Assumes frontend, backend, and IB Gateway are on the same machine. For more details, see [`Deployment.md`](./Deployment.md).

1. Build and run IB Gateway:
```shell
cd ib-gateway
docker build --platform=linux/amd64 -t ib-gateway:local .
docker network create ibkr-net
docker run -d --name ib-gateway --network ibkr-net -p 4001:4001 -p 5901:5901 -p 6080:6080 ib-gateway:local
```

1. IB Gateway UI settings: `configuration -> Settings -> API -> Settings`
- Set `Trusted IPs` to the backend container IP.
- Uncheck `Read-Only API`.

1. Prepare Postgres and set `IBKR_DATABASE_URL`.

2. Build and run backend:
```shell
cd backend
docker build -t ibkr-backend:local .
docker run -d --name ibkr-backend \
  --network ibkr-net \
  --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://USER:PASS@HOST:5432/DB \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```

1. Build and run frontend:
```shell
cd frontend
docker build -t ibkr-frontend:lan .
docker run -d --name ibkr-frontend --network ibkr-net -p 80:80 ibkr-frontend:lan
```

**Notes**
- If IB Gateway is in Docker, do not use `127.0.0.1` from the backend. Use the container name on the same Docker network.
- Frontend proxies API/WS to backend via `/api`, so run frontend on `ibkr-net` to reach `ibkr-backend:8000`.
- IB Gateway exposed ports:
  - `4001`: IB Gateway API port used by backend (`IBKR_HOST`/`IBKR_PORT`).
  - `5901`: VNC TCP port for native VNC clients.
  - `6080`: noVNC/websockify browser access (for web login and 2FA operations).
- If your host uses a proxy, allow direct access for `ibkr.com` and `ibllc.com`.
- Logging in to the same IBKR account from other clients (web/mobile) may disconnect IB Gateway. Use VNC to reconnect.
- IBKR trade events must be on the same connection as order placement. Placing orders elsewhere may cause missing trade events here.

**Details**
For architecture and behavior details, see [`Details.md`](./Details.md).

## 中文

IBKR PnL Tracker 是一个面向 Interactive Brokers 的实时盈亏看板。它连接 IB Gateway，将实时数据优先写入内存，并仅在需要时周期性落库，从而降低数据库读写压力。前端通过 WebSocket 获取实时数据，通过 REST 接口获取快照数据。

![仪表盘概览](./image.png)

**核心功能**
- 实时持仓、历史持、当日盈亏与总盈亏展示（WebSocket 实时更新）。
- Total PnL 趋势图，支持悬浮查看数值。
- 账户健康度指标（净清算值、可用资金、保证金需求等）。
- Gateway 与 IBKR 服务器连接状态区分显示。
- 下单面板（市价/限价），并返回下单状态反馈。
- 每个持仓支持交易明细展开，手续费合计前端计算展示。

**数据流**
- IB Gateway 推送持仓、PnL 与账户汇总数据到后端。
- 后端使用内存缓存提升读性能，并降低 DB 写入频率。
- 前端实时数据来自 WebSocket，快照数据来自 REST 接口。

**适用场景**
- 集中监控实时持仓与盈亏。
- 查看每日盈亏趋势与累计变化。
- 快速判断账户流动性与风险水平。

**当前持仓字段说明**
- `Symbol`：标的代码。
- `Time`：开仓时间（北京时间）。
- `Qty`：持仓数量。
- `Avg Cost`：平均成本。
- `Value`：`Qty * Avg Cost`（前端计算，不落库）。
- `Daily`：该持仓当日盈亏。
- `Realized`：该持仓已实现盈亏。
- `Unrealized`：该持仓未实现盈亏；下方百分比为 `Unrealized / |Qty * Avg Cost|`。
- `FEE`：该持仓关联的成交手续费合计（前端计算）。
- `Total`：该持仓总盈亏；下方百分比为 `Total / |Qty * Avg Cost|`。

**历史持仓**
已平仓的持仓会显示在 `Historical Positions` 列表，包含开/平仓时间与已实现盈亏。点击展开可查看该持仓的成交明细。

**快速开始（单机 Docker）**
默认前端、后端、IB Gateway 部署在同一台机器。更详细说明见 [`Deployment.md`](./Deployment.md)。

1. 构建并启动 IB Gateway：
```shell
cd ib-gateway
docker build --platform=linux/amd64 -t ib-gateway:local .
docker network create ibkr-net
docker run -d --name ib-gateway --network ibkr-net -p 4001:4001 -p 5901:5901 -p 6080:6080 ib-gateway:local
```

1. IB Gateway 后台设置：`configuration -> Settings -> API -> Settings`
- `Trusted IPs` 填 backend 容器 IP。
- 取消勾选 `Read-Only API`。

1. 准备 PostgreSQL，并设置 `IBKR_DATABASE_URL`。

2. 构建并启动后端：
```shell
cd backend
docker build -t ibkr-backend:local .
docker run -d --name ibkr-backend \
  --network ibkr-net \
  --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://USER:PASS@HOST:5432/DB \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```

1. 构建并启动前端：
```shell
cd frontend
docker build -t ibkr-frontend:lan .
docker run -d --name ibkr-frontend --network ibkr-net -p 80:80 ibkr-frontend:lan
```

**注意事项**
- 如果 IB Gateway 在 Docker 里，后端不要用 `127.0.0.1`，请使用同一网络下的容器名。
- 前端通过 `/api` 反向代理到后端，请将前端容器加入 `ibkr-net`，以访问 `ibkr-backend:8000`。
- IB Gateway 暴露端口说明：
  - `4001`：IB Gateway API 端口，后端通过 `IBKR_HOST`/`IBKR_PORT` 连接。
  - `5901`：VNC 原生 TCP 端口，供 VNC 客户端连接。
  - `6080`：noVNC/websockify 网页入口，用于浏览器登录和 2FA 操作。
- 如果机器使用代理，需要对 `ibkr.com`、`ibllc.com` 走直连。
- 如果在其他客户端（网页/手机）登录同一 IBKR 账号，可能导致 IB Gateway 断开，需要通过 VNC 点击 reconnect。
- 交易事件监听与下单必须在同一连接，否则在其他地方下单可能导致本系统收不到成交事件。

**技术细节**
如需更深入的架构与行为说明，请参考 [`Details.md`](./Details.md)。
