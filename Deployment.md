# IBKR PnL Tracker

[English](#english) | [中文](#中文)

## English

## Local/LAN Deployment (Single Host)

Assumption: frontend, backend, and IB Gateway run on the same machine.

### 1) Deploy IB Gateway

```shell
cd ~/workspace/ibkr-pnl-tracker/ib-gateway
docker build --platform=linux/amd64 -t ib-gateway:local .
docker network create ibkr-net
docker run -d --name ib-gateway --network ibkr-net -p 4001:4001 -p 5900:5900 -p 6080:6080 ib-gateway:local
```

Ports: `4001` for IB Gateway API, `5900/6080` for VNC/web login and 2FA.

### 1.1) IB Gateway UI Settings

Go to `configuration -> Settings -> API -> Settings`.

1. Set `Trusted IPs` to the backend container IP.
2. Uncheck `Read-Only API`.

### 2) Create PostgreSQL Database

Set database connection info:

```shell
USER_NAME=
PASS=
SERVER=
DB=
```

### 3) Backend

```shell
cd ~/workspace/ibkr-pnl-tracker/backend
docker build -t ibkr-backend:local \
 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
 .

docker run -d --name ibkr-backend \
  --network ibkr-net \
  --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://$USER_NAME:$PASS@$SERVER/$DB \
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
docker run -d --name ib-gateway --network ibkr-net -p 4001:4001 -p 5900:5900 -p 6080:6080 ib-gateway:local
docker run -d --name ibkr-backend \
  --network ibkr-net \
    --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=<IBKR_DATABASE_URL> \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```

Then set `Trusted IPs` in IB Gateway to `172.18.0.11` (CIDR not supported).

### 4) Frontend

```shell
cd ~/workspace/ibkr-pnl-tracker/frontend
docker build -t ibkr-frontend:lan \
  --build-arg VITE_API_BASE=http://192.168.50.119:8000 .
docker run -d --name ibkr-frontend -p 80:80 ibkr-frontend:lan
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

### 1) 部署 IB Gateway

```shell
cd ~/workspace/ibkr-pnl-tracker/ib-gateway
docker build --platform=linux/amd64 -t ib-gateway:local .
docker network create ibkr-net
docker run -d --name ib-gateway --network ibkr-net -p 4001:4001 -p 5900:5900 -p 6080:6080 ib-gateway:local
```

说明：端口 `4001` 为 IB Gateway API，`5900/6080` 用于 VNC/网页版登录和 2FA。  

### 1.1) IB Gateway 后台设置

进入 configuration -> Settings -> API -> Settings

1. Trusted IPs 填 backend 容器的ip地址
2. 取消勾选 "Read-Only API"

### 2) 创建 PostgreSQL 数据库

设置数据库连接信息

```shell
USER_NAME=
PASS=
SERVER=
DB=
```

### 3) 后端

```shell
cd ~/workspace/ibkr-pnl-tracker/backend
docker build -t ibkr-backend:local \
 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
 .

docker run -d --name ibkr-backend \
  --network ibkr-net \
  --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=postgresql://$USER_NAME:$PASS@$SERVER/$DB \
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
docker run -d --name ib-gateway --network ibkr-net -p 4001:4001 -p 5900:5900 -p 6080:6080 ib-gateway:local
docker run -d --name ibkr-backend \
  --network ibkr-net \
    --ip 172.18.0.11 \
  -p 8000:8000 \
  -e IBKR_DATABASE_URL=<IBKR_DATABASE_URL> \
  -e IBKR_HOST=ib-gateway \
  -e IBKR_PORT=4001 \
  -e IBKR_READONLY=false \
  ibkr-backend:local
```

然后在ib gateway后台设置Trusted IPs 为 172.18.0.11 (不支持CIDR)

### 4) 前端

```shell
cd ~/workspace/ibkr-pnl-tracker/frontend
docker build -t ibkr-frontend:lan \
  --build-arg VITE_API_BASE=http://192.168.50.119:8000 .
docker run -d --name ibkr-frontend -p 80:80 ibkr-frontend:lan
```

### 其他

ib gateway所在的机器如果使用了代理，需要加上这两个规则，也就是让ib的域名直连，否则无法访问。

```yaml
- DOMAIN-SUFFIX,ibllc.com, 🎯 全球直连
- DOMAIN-SUFFIX,ibkr.com, 🎯 全球直连
```
