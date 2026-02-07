from __future__ import annotations

import asyncio
import datetime as dt
import sqlite3
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import load_settings
from .db import get_connection, init_db, upsert_account
from .ibkr_sync import IBKRSyncManager, seed_demo_data
from .k8s import restart_deployment
from .pnl import get_account_summary, get_history_positions, get_positions


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


def _get_default_account(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute("SELECT id, ibkr_account, base_currency FROM accounts LIMIT 1").fetchone()
    if row:
        return {"id": int(row["id"]), "account": row["ibkr_account"], "base_currency": row["base_currency"]}
    account_id = upsert_account(conn, "LOCAL", settings.base_currency)
    return {"id": account_id, "account": "LOCAL", "base_currency": settings.base_currency}


@app.on_event("startup")
async def startup() -> None:
    init_db(settings.db_path)
    app.state.sync_manager = IBKRSyncManager(settings)
    if settings.ib_auto_sync:
        app.state.sync_manager.start()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "time": _utc_now()}


@app.post("/sync/start")
def sync_start() -> Dict[str, Any]:
    status = app.state.sync_manager.start()
    return {
        "running": status.running,
        "connected": status.connected,
        "started_at": status.started_at,
        "last_connected_at": status.last_connected_at,
        "last_disconnected_at": status.last_disconnected_at,
        "error": status.error,
    }


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
        "vnc_url": settings.gateway_vnc_url,
    }


@app.post("/gateway/restart")
def gateway_restart() -> Dict[str, Any]:
    if not settings.gateway_restart_enabled:
        raise HTTPException(status_code=400, detail="Gateway restart disabled")
    try:
        restart_deployment(settings.gateway_deployment, settings.gateway_namespace)
        return {
            "status": "restarting",
            "deployment": settings.gateway_deployment,
            "namespace": settings.gateway_namespace,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/sync/demo")
def sync_demo() -> Dict[str, str]:
    seed_demo_data(settings)
    return {"status": "demo seeded"}


@app.get("/positions")
def positions() -> List[Dict[str, Any]]:
    with get_connection(settings.db_path) as conn:
        account = _get_default_account(conn)
        return get_positions(conn, account["id"], account["base_currency"])


@app.get("/positions/history")
def positions_history() -> List[Dict[str, Any]]:
    with get_connection(settings.db_path) as conn:
        account = _get_default_account(conn)
        return get_history_positions(conn, account["id"], account["base_currency"])


@app.get("/pnl/summary")
def pnl_summary() -> Dict[str, Any]:
    with get_connection(settings.db_path) as conn:
        account = _get_default_account(conn)
        return get_account_summary(conn, account["id"], account["base_currency"])


@app.get("/trades")
def trades() -> List[Dict[str, Any]]:
    with get_connection(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT symbol, exchange, currency, side, qty, price, commission, realized_pnl, trade_time
            FROM trades
            ORDER BY trade_time DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/positions/{position_id}/trades")
def trades_for_position(position_id: int) -> List[Dict[str, Any]]:
    with get_connection(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT symbol, exchange, currency, side, qty, price, commission, realized_pnl, trade_time
            FROM trades
            WHERE position_id = ?
            ORDER BY trade_time ASC
            """,
            (position_id,),
        ).fetchall()
        return [dict(row) for row in rows]


@app.websocket("/ws/updates")
async def updates(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            with get_connection(settings.db_path) as conn:
                account = _get_default_account(conn)
                payload = {
                    "summary": get_account_summary(conn, account["id"], account["base_currency"]),
                    "positions": get_positions(conn, account["id"], account["base_currency"]),
                    "history": get_history_positions(conn, account["id"], account["base_currency"]),
                }
            await ws.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
