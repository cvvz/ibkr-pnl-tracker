from __future__ import annotations

import asyncio
import datetime as dt
import psycopg
import threading
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import load_settings
from .cache import CacheStore
from .db import get_connection, init_db, upsert_account
from .ibkr_sync import IBKRSyncManager, OrderPayload
from .pnl import (
    get_account_snapshot,
    get_account_summary,
    get_history_positions,
    get_positions,
    get_total_pnl_series,
)


settings = load_settings()
app = FastAPI(title="IBKR PnL Tracker")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _format_bj(value: str) -> str:
    if not value:
        return value
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    bj = parsed.astimezone(dt.timezone(dt.timedelta(hours=8)))
    return bj.strftime("%Y-%m-%d %H:%M:%S")


def _normalize_side_value(side: str) -> str:
    normalized = side.strip().lower()
    if normalized in {"bot", "buy"}:
        return "buy"
    if normalized in {"sld", "sell"}:
        return "sell"
    return normalized


def _get_default_account(conn: psycopg.Connection) -> Dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT a.id, a.ibkr_account, a.base_currency
        FROM accounts a
        WHERE a.id IN (SELECT account_id FROM positions)
        LIMIT 1
        """
    ).fetchone()
    if row:
        return {"id": int(row["id"]), "account": row["ibkr_account"], "base_currency": row["base_currency"]}

    row = conn.execute(
        """
        SELECT a.id, a.ibkr_account, a.base_currency
        FROM accounts a
        WHERE a.id IN (SELECT account_id FROM positions_history)
        LIMIT 1
        """
    ).fetchone()
    if row:
        return {"id": int(row["id"]), "account": row["ibkr_account"], "base_currency": row["base_currency"]}

    row = conn.execute(
        """
        SELECT a.id, a.ibkr_account, a.base_currency
        FROM accounts a
        WHERE a.id IN (SELECT account_id FROM trades)
        LIMIT 1
        """
    ).fetchone()
    if row:
        return {"id": int(row["id"]), "account": row["ibkr_account"], "base_currency": row["base_currency"]}

    row = conn.execute("SELECT id, ibkr_account, base_currency FROM accounts LIMIT 1").fetchone()
    if row:
        return {"id": int(row["id"]), "account": row["ibkr_account"], "base_currency": row["base_currency"]}
    return None


def _cache_ready() -> bool:
    cache = getattr(app.state, "cache", None)
    return bool(cache and cache.is_initialized())


class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    qty: float = Field(..., gt=0)
    side: Literal["buy", "sell", "BUY", "SELL"]
    order_type: Literal["MKT", "LMT", "MARKET", "LIMIT"]
    price: Optional[float] = Field(default=None, gt=0)
    exchange: Optional[str] = "SMART"
    currency: Optional[str] = "USD"
    account: Optional[str] = None
    tif: Optional[str] = None
    idempotency_key: Optional[str] = None


@app.on_event("startup")
async def startup() -> None:
    init_db(settings.database_url)
    app.state.cache = CacheStore()
    app.state.sync_manager = IBKRSyncManager(settings, cache=app.state.cache)
    app.state.order_idempotency = {}
    app.state.order_idempotency_lock = threading.Lock()
    with get_connection(settings.database_url) as conn:
        upsert_account(conn, "LOCAL", settings.base_currency)
        account = _get_default_account(conn)
        if account:
            app.state.cache.load_from_db(conn, account["id"], account["base_currency"])
    if settings.ib_auto_sync:
        app.state.sync_manager.start()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "time": _utc_now()}


@app.post("/sync/stop")
def sync_stop() -> Dict[str, Any]:
    status = app.state.sync_manager.stop()
    return {
        "running": status.running,
        "connected": status.connected,
        "started_at": status.started_at,
        "last_connected_at": status.last_connected_at,
        "last_disconnected_at": status.last_disconnected_at,
        "error": status.error,
    }


@app.get("/sync/status")
def sync_status() -> Dict[str, Any]:
    status = app.state.sync_manager.status()
    return {
        "running": status.running,
        "connected": status.connected,
        "started_at": status.started_at,
        "last_connected_at": status.last_connected_at,
        "last_disconnected_at": status.last_disconnected_at,
        "last_update": status.last_update,
        "error": status.error,
        "ibkr_connected": status.ibkr_connected,
        "ibkr_last_connected_at": status.ibkr_last_connected_at,
        "ibkr_last_disconnected_at": status.ibkr_last_disconnected_at,
    }


@app.get("/sync/health")
def sync_health() -> Dict[str, Any]:
    status = app.state.sync_manager.status()
    return {
        "running": status.running,
        "connected": status.connected,
        "started_at": status.started_at,
        "last_connected_at": status.last_connected_at,
        "last_disconnected_at": status.last_disconnected_at,
        "last_update": status.last_update,
        "error": status.error,
        "ibkr_connected": status.ibkr_connected,
        "ibkr_last_connected_at": status.ibkr_last_connected_at,
        "ibkr_last_disconnected_at": status.ibkr_last_disconnected_at,
    }


@app.post("/orders")
def place_order(
    payload: OrderRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> Dict[str, Any]:
    if settings.ib_readonly:
        raise HTTPException(status_code=400, detail="IBKR_READONLY is enabled")
    status = app.state.sync_manager.status()
    if not status.connected:
        raise HTTPException(status_code=400, detail="IB Gateway disconnected")

    key = idempotency_key or payload.idempotency_key
    if key:
        with app.state.order_idempotency_lock:
            now = time.time()
            stale_keys = [
                k for k, v in app.state.order_idempotency.items() if now - v["ts"] > 3600
            ]
            for k in stale_keys:
                app.state.order_idempotency.pop(k, None)
            entry = app.state.order_idempotency.get(key)
            if entry:
                if entry["status"] == "completed":
                    return entry["response"]
                return {"status": "pending", "request_id": entry["request_id"]}

    payload_obj = OrderPayload(
        symbol=payload.symbol,
        qty=float(payload.qty),
        side=_normalize_side_value(payload.side),
        order_type=payload.order_type,
        price=float(payload.price) if payload.price is not None else None,
        exchange=payload.exchange,
        currency=payload.currency,
        tif=payload.tif,
        account=payload.account,
    )
    request_id = None
    if key:
        request_id = key
        with app.state.order_idempotency_lock:
            app.state.order_idempotency[key] = {
                "status": "pending",
                "request_id": request_id,
                "ts": time.time(),
            }

    result = app.state.sync_manager.enqueue_order(payload_obj, request_id=request_id)
    if not result.success:
        if key:
            with app.state.order_idempotency_lock:
                app.state.order_idempotency.pop(key, None)
        raise HTTPException(status_code=400, detail=result.error or "Order failed")
    response = result.result or {"status": "queued", "request_id": result.request_id}
    if key:
        with app.state.order_idempotency_lock:
            status_value = "completed"
            if response.get("status") == "queued":
                status_value = "pending"
            app.state.order_idempotency[key] = {
                "status": status_value,
                "request_id": response.get("request_id", request_id),
                "response": response,
                "ts": time.time(),
            }
    return response


@app.get("/positions")
def positions() -> List[Dict[str, Any]]:
    if _cache_ready():
        return app.state.cache.snapshot_positions()
    with get_connection(settings.database_url) as conn:
        account = _get_default_account(conn)
        if not account:
            return []
        return get_positions(conn, account["id"], account["base_currency"])


@app.get("/positions/history")
def positions_history() -> List[Dict[str, Any]]:
    if _cache_ready():
        return app.state.cache.snapshot_history()
    with get_connection(settings.database_url) as conn:
        account = _get_default_account(conn)
        if not account:
            return []
        return get_history_positions(conn, account["id"], account["base_currency"])


@app.get("/pnl/summary")
def pnl_summary() -> Dict[str, Any]:
    if _cache_ready():
        return app.state.cache.snapshot_account_pnl()
    with get_connection(settings.database_url) as conn:
        account = _get_default_account(conn)
        if not account:
            return {
                "account_id": None,
                "base_currency": settings.base_currency,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "daily_pnl": 0.0,
                "total_pnl": 0.0,
                "as_of": _utc_now(),
            }
        return get_account_summary(conn, account["id"], account["base_currency"])


@app.get("/account/summary")
def account_summary() -> Dict[str, Any]:
    if _cache_ready():
        return app.state.cache.snapshot_account_summary()
    with get_connection(settings.database_url) as conn:
        account = _get_default_account(conn)
        if not account:
            return {
                "account_id": None,
                "base_currency": settings.base_currency,
                "net_liquidation": None,
                "total_cash_value": None,
                "available_funds": None,
                "excess_liquidity": None,
                "init_margin_req": None,
                "maint_margin_req": None,
                "gross_position_value": None,
                "short_market_value": None,
                "as_of": _utc_now(),
            }
        return get_account_snapshot(conn, account["id"], account["base_currency"])


@app.get("/pnl/total-trend")
def total_trend() -> List[Dict[str, Any]]:
    if _cache_ready():
        return app.state.cache.snapshot_total_pnl_trend()
    with get_connection(settings.database_url) as conn:
        account = _get_default_account(conn)
        if not account:
            return []
        return get_total_pnl_series(conn, account["id"])


@app.get("/trades")
def trades() -> List[Dict[str, Any]]:
    with get_connection(settings.database_url) as conn:
        rows = conn.execute(
            """
            SELECT symbol, exchange, currency, side, qty, price, commission, realized_pnl, trade_time, perm_id
            FROM trades
            ORDER BY trade_time DESC
            """
        ).fetchall()
        payload = []
        for row in rows:
            item = dict(row)
            item["trade_time"] = _format_bj(item.get("trade_time", ""))
            payload.append(item)
        return payload


@app.get("/positions/{position_id}/trades")
def trades_for_position(position_id: int) -> List[Dict[str, Any]]:
    with get_connection(settings.database_url) as conn:
        row = conn.execute(
            """
            SELECT account_id, symbol, exchange, currency, open_time, NULL AS close_time
            FROM positions
            WHERE id = %s
            """,
            (position_id,),
        ).fetchone()
        if not row:
            row = conn.execute(
                """
                SELECT account_id, symbol, exchange, currency, open_time, close_time
                FROM positions_history
                WHERE id = %s
                """,
                (position_id,),
            ).fetchone()
        if not row:
            return []

        query = """
            SELECT trade_time, side, qty, price, commission, realized_pnl
            FROM trades
            WHERE account_id = %s AND symbol = %s AND currency = %s
        """
        params: List[Any] = [row["account_id"], row["symbol"], row["currency"]]
        if row["open_time"]:
            query += " AND trade_time >= %s"
            params.append(row["open_time"])
        if row["close_time"]:
            query += " AND trade_time <= %s"
            params.append(row["close_time"])
        query += " ORDER BY trade_time ASC"
        rows = conn.execute(query, params).fetchall()
        payload = []
        for row in rows:
            item = dict(row)
            item["trade_time"] = _format_bj(item.get("trade_time", ""))
            payload.append(item)
        return payload


@app.websocket("/ws/updates")
async def updates(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            if _cache_ready():
                payload = {
                    "pnl_summary": app.state.cache.snapshot_account_pnl(),
                    "positions": app.state.cache.snapshot_positions(),
                    "history": app.state.cache.snapshot_history(),
                    "total_pnl_trend": app.state.cache.snapshot_total_pnl_trend(),
                    "account_summary": app.state.cache.snapshot_account_summary(),
                }
            else:
                with get_connection(settings.database_url) as conn:
                    account = _get_default_account(conn)
                    if not account:
                        payload = {
                            "pnl_summary": {
                                "account_id": None,
                                "base_currency": settings.base_currency,
                                "realized_pnl": 0.0,
                                "unrealized_pnl": 0.0,
                                "daily_pnl": 0.0,
                                "total_pnl": 0.0,
                                "as_of": _utc_now(),
                            },
                            "positions": [],
                            "history": [],
                            "total_pnl_trend": [],
                            "account_summary": {
                                "account_id": None,
                                "base_currency": settings.base_currency,
                                "net_liquidation": None,
                                "total_cash_value": None,
                                "available_funds": None,
                                "excess_liquidity": None,
                                "init_margin_req": None,
                                "maint_margin_req": None,
                                "gross_position_value": None,
                                "short_market_value": None,
                                "as_of": _utc_now(),
                            },
                        }
                    else:
                        payload = {
                            "pnl_summary": get_account_summary(
                                conn, account["id"], account["base_currency"]
                            ),
                            "positions": get_positions(conn, account["id"], account["base_currency"]),
                            "history": get_history_positions(conn, account["id"], account["base_currency"]),
                            "total_pnl_trend": get_total_pnl_series(conn, account["id"]),
                            "account_summary": get_account_snapshot(
                                conn, account["id"], account["base_currency"]
                            ),
                        }
            await ws.send_json(payload)
            await asyncio.sleep(settings.ws_update_interval_seconds)
    except WebSocketDisconnect:
        return
