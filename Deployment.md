# IBKR PnL Tracker

[English](#english) | [中文](#中文)

## English

## Local/LAN Deployment (Single Host)

Assumption: frontend, backend, and IB Gateway run on the same machine.

### 0) Docker Compose (Recommended, includes local Postgres)

```shell
cd ~/workspace/ibkr-pnl-tracker
cp .env.compose.example .env
docker compose up -d --build
```

After startup, configure IB Gateway via noVNC (`http://localhost:6080`):

1. Go to `configuration -> Settings -> API -> Settings`.
2. Set `Trusted IPs` to backend container IP:
   `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ibkr-backend`
3. Uncheck `Read-Only API`.
4. For overnight orders, also update `configuration -> Settings -> API -> Precautions` to allow direct-routed overnight orders (otherwise `Error 10329` may occur).

Compose env names:
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_DB`: database connection config.
- `IBKR_BASE_CURRENCY`, `IBKR_PORT`, `IBKR_READONLY`, `IBKR_AUTO_SYNC`: backend runtime options.
- `VNC_PASSWORD`, `PIP_INDEX_URL`: optional.

### 1) Deploy IB Gateway

```shell
cd ~/workspace/ibkr-pnl-tracker/ib-gateway
docker build --platform=linux/amd64 -t ib-gateway:local .
docker network create ibkr-net
docker run -d --name ib-gateway \
    --restart unless-stopped \
    --network ibkr-net -p 4001:4001 -p 5901:5901 -p 6080:6080 ib-gateway:local
```

Port usage:
- `4001`: IB Gateway API port used by backend (`IBKR_HOST`/`IBKR_PORT`).
- `5901`: VNC TCP port for native VNC clients.
- `6080`: noVNC/websockify browser access (for web login and 2FA operations).
- On macOS, system Screen Sharing/Remote Management commonly uses `5900`; keeping container VNC on `5901` helps avoid local port conflicts.

### 1.1) IB Gateway UI Settings

Go to `configuration -> Settings -> API -> Settings`.

1. Set `Trusted IPs` to the backend container IP.
2. Uncheck `Read-Only API`.

For overnight order routing, also check `configuration -> Settings -> API -> Precautions`.

3. Allow API direct-routed overnight orders (or disable the related precaution restriction).
4. If blocked by Precautions, IB Gateway may reject with `Error 10329` (`directly routed to OVERNIGHT`).

### 2) Create PostgreSQL Database

Set database connection info:

```shell
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_HOST=
POSTGRES_DB=
```

### 3) Backend

```shell
cd ~/workspace/ibkr-pnl-tracker/backend
docker build -t ibkr-backend:local \
 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
 .

docker run -d --name ibkr-backend \
  --restart unless-stopped \
  --network ibkr-net \
  --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:5432/$POSTGRES_DB \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```

#### Container Networking Notes

If IB Gateway runs in Docker, the backend container must not connect via `127.0.0.1`. Use a custom Docker network and connect by container name.

Example (same Docker network):

```shell
docker network create ibkr-net
docker run -d --name ib-gateway \
    --restart unless-stopped \
    --network ibkr-net -p 4001:4001 -p 5901:5901 -p 6080:6080 ib-gateway:local
docker run -d --name ibkr-backend \
  --restart unless-stopped \
  --network ibkr-net \
    --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:5432/$POSTGRES_DB \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```

Then set `Trusted IPs` in IB Gateway to the current backend container IP (CIDR not supported), for example:

```shell
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ibkr-backend
```

### 4) Frontend

```shell
cd ~/workspace/ibkr-pnl-tracker/frontend
docker build -t ibkr-frontend:lan .
docker run -d --name ibkr-frontend \
    --restart unless-stopped \
    --network ibkr-net -p 80:80 ibkr-frontend:lan
```

### Notes

If the IB Gateway host uses a proxy, allow direct access for these domains:

```yaml
- DOMAIN-SUFFIX,ibllc.com, 🎯 Direct
- DOMAIN-SUFFIX,ibkr.com, 🎯 Direct
```

## 中文

## 本地/局域网部署（单机）

默认假设：前端、后端、IB Gateway 部署在同一台机器

### 0) Docker Compose（一键，内置本地 Postgres）

```shell
cd ~/workspace/ibkr-pnl-tracker
cp .env.compose.example .env
docker compose up -d --build
```

启动后通过 noVNC（`http://localhost:6080`）配置 IB Gateway：

1. 进入 `configuration -> Settings -> API -> Settings`
2. `Trusted IPs` 填后端容器当前 IP：
   `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ibkr-backend`
3. 取消勾选 `Read-Only API`
4. 夜盘下单需在 `configuration -> Settings -> API -> Precautions` 放开 API 直连夜盘限制（否则可能报 `10329`）

Compose 环境变量说明：
- `POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_HOST`、`POSTGRES_DB`：数据库连接配置
- `IBKR_BASE_CURRENCY`、`IBKR_PORT`、`IBKR_READONLY`、`IBKR_AUTO_SYNC`：后端运行参数
- `VNC_PASSWORD`、`PIP_INDEX_URL`：可选

### 1) 部署 IB Gateway

```shell
cd ~/workspace/ibkr-pnl-tracker/ib-gateway
docker build --platform=linux/amd64 -t ib-gateway:local .
docker network create ibkr-net
docker run -d --name ib-gateway \
    --restart unless-stopped \
    --network ibkr-net -p 4001:4001 -p 5901:5901 -p 6080:6080 ib-gateway:local
```

端口用途说明：
- `4001`：IB Gateway API 端口，后端通过 `IBKR_HOST`/`IBKR_PORT` 连接。
- `5901`：VNC 原生 TCP 端口，供 VNC 客户端连接。
- `6080`：noVNC/websockify 网页入口，用于浏览器登录和 2FA 操作。  
- 在 macOS 上，系统屏幕共享/远程管理通常占用 `5900`；这里默认使用 `5901` 可以避免本地端口冲突。

### 1.1) IB Gateway 后台设置

进入 configuration -> Settings -> API -> Settings

1. Trusted IPs 填 backend 容器的ip地址
2. 取消勾选 "Read-Only API"

夜盘下单还需要检查 `configuration -> Settings -> API -> Precautions`

3. 放开 API 直连夜盘路由（或关闭对应 precaution 限制）
4. 若未放开，IB Gateway 可能返回 `Error 10329`（`directly routed to OVERNIGHT`）

### 2) 创建 PostgreSQL 数据库

设置数据库连接信息

```shell
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_HOST=
POSTGRES_DB=
```

### 3) 后端

```shell
# 设置数据库连接信息
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_HOST=
POSTGRES_DB=


cd ~/workspace/ibkr-pnl-tracker/backend
docker build -t ibkr-backend:local \
 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
 .

docker run -d --name ibkr-backend \
  --restart unless-stopped \
  --network ibkr-net \
  --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:5432/$POSTGRES_DB \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```

#### 容器互联注意

如果 **IB Gateway 在容器里**，后端容器不能用 `127.0.0.1` 连接它。推荐创建自定义网络，后端用容器名连接

示例（同一 Docker 网络）：

```shell
docker network create ibkr-net
docker run -d --name ib-gateway \
    --restart unless-stopped \
    --network ibkr-net -p 4001:4001 -p 5901:5901 -p 6080:6080 ib-gateway:local
docker run -d --name ibkr-backend \
  --restart unless-stopped \
  --network ibkr-net \
    --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:5432/$POSTGRES_DB \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```

然后在 ib gateway 后台将 Trusted IPs 设置为后端容器当前 IP（不支持 CIDR），例如：

```shell
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ibkr-backend
```

### 4) 前端

```shell
cd ~/workspace/ibkr-pnl-tracker/frontend
docker build -t ibkr-frontend:lan .
docker run -d --name ibkr-frontend \
    --restart unless-stopped \
    --network ibkr-net -p 80:80 ibkr-frontend:lan
```

### 其他

ib gateway所在的机器如果使用了代理，需要加上这两个规则，也就是让ib的域名直连，否则无法访问。

```yaml
- DOMAIN-SUFFIX,ibllc.com, 🎯 全球直连
- DOMAIN-SUFFIX,ibkr.com, 🎯 全球直连
```
