from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Dict, List


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _get_fx_rate(conn: sqlite3.Connection, from_ccy: str, to_ccy: str) -> float:
    if from_ccy == to_ccy:
        return 1.0
    row = conn.execute(
        "SELECT rate FROM fx_rates WHERE from_ccy = ? AND to_ccy = ?",
        (from_ccy, to_ccy),
    ).fetchone()
    return float(row["rate"]) if row else 1.0


def _get_price(conn: sqlite3.Connection, symbol: str, exchange: str | None, currency: str) -> float | None:
    exchange = exchange or ""
    row = conn.execute(
        """
        SELECT last, bid, ask FROM prices
        WHERE symbol = ? AND exchange = ? AND currency = ?
        """,
        (symbol, exchange, currency),
    ).fetchone()
    if not row:
        return None
    for key in ("last", "bid", "ask"):
        if row[key] is not None:
            return float(row[key])
    return None


def _row_to_position(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    base_currency: str,
    is_history: bool = False,
) -> Dict:
    price = None if is_history else _get_price(conn, row["symbol"], row["exchange"], row["currency"])
    fx_rate = _get_fx_rate(conn, row["currency"], base_currency)
    qty = float(row["qty"])
    avg_cost = float(row["avg_cost"])
    unrealized = 0.0
    if price is not None:
        unrealized = (price - avg_cost) * qty
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "exchange": row["exchange"],
        "currency": row["currency"],
        "qty": qty,
        "avg_cost": avg_cost,
        "market_price": price,
        "realized_pnl": float(row["realized_pnl"]) * fx_rate,
        "unrealized_pnl": unrealized * fx_rate,
        "total_pnl": (float(row["realized_pnl"]) + unrealized) * fx_rate,
        "fx_rate": fx_rate,
        "open_time": row["open_time"],
        "close_time": row["close_time"] if "close_time" in row.keys() else None,
        "updated_at": row["updated_at"],
    }


def get_positions(conn: sqlite3.Connection, account_id: int, base_currency: str) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time, updated_at
        FROM positions
        WHERE account_id = ?
        ORDER BY symbol
        """,
        (account_id,),
    ).fetchall()

    return [_row_to_position(conn, row, base_currency, is_history=False) for row in rows]


def get_history_positions(conn: sqlite3.Connection, account_id: int, base_currency: str) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time, close_time, updated_at
        FROM positions_history
        WHERE account_id = ?
        ORDER BY close_time DESC
        """,
        (account_id,),
    ).fetchall()

    return [_row_to_position(conn, row, base_currency, is_history=True) for row in rows]


def get_account_summary(conn: sqlite3.Connection, account_id: int, base_currency: str) -> Dict:
    positions = get_positions(conn, account_id, base_currency)
    history = get_history_positions(conn, account_id, base_currency)

    realized_total = sum(item["realized_pnl"] for item in positions) + sum(
        item["realized_pnl"] for item in history
    )
    unrealized_total = sum(item["unrealized_pnl"] for item in positions)

    return {
        "account_id": account_id,
        "base_currency": base_currency,
        "realized_pnl": realized_total,
        "unrealized_pnl": unrealized_total,
        "total_pnl": realized_total + unrealized_total,
        "as_of": _utc_now(),
    }


def record_snapshot(conn: sqlite3.Connection, account_id: int, base_currency: str) -> None:
    summary = get_account_summary(conn, account_id, base_currency)
    conn.execute(
        """
        INSERT INTO pnl_snapshots (account_id, timestamp, realized_pnl, unrealized_pnl, total_pnl)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            account_id,
            summary["as_of"],
            summary["realized_pnl"],
            summary["unrealized_pnl"],
            summary["total_pnl"],
        ),
    )
    conn.commit()
