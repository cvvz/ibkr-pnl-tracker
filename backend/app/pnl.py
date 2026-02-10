from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Dict, List


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _sum_realized(
    conn: sqlite3.Connection,
    account_id: int,
    symbol: str,
    currency: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> float:
    query = """
        SELECT COALESCE(SUM(realized_pnl), 0) AS total
        FROM trades
        WHERE account_id = ? AND symbol = ? AND currency = ?
    """
    params: List[object] = [account_id, symbol, currency]
    if start_time:
        query += " AND trade_time >= ?"
        params.append(start_time)
    if end_time:
        query += " AND trade_time <= ?"
        params.append(end_time)
    row = conn.execute(query, params).fetchone()
    return float(row["total"]) if row else 0.0


def get_positions(conn: sqlite3.Connection, account_id: int, base_currency: str) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT id, symbol, exchange, currency, qty, avg_cost, unrealized_pnl, open_time
        FROM positions
        WHERE account_id = ?
        ORDER BY symbol
        """,
        (account_id,),
    ).fetchall()

    positions: List[Dict] = []
    for row in rows:
        realized = _sum_realized(
            conn,
            account_id,
            row["symbol"],
            row["currency"],
            start_time=row["open_time"],
        )
        unrealized = float(row["unrealized_pnl"])
        positions.append(
            {
                "id": row["id"],
                "symbol": row["symbol"],
                "qty": float(row["qty"]),
                "avg_cost": float(row["avg_cost"]),
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "total_pnl": realized + unrealized,
                "open_time": row["open_time"],
            }
        )
    return positions


def get_history_positions(conn: sqlite3.Connection, account_id: int, base_currency: str) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT id, symbol, exchange, currency, open_time, close_time
        FROM positions_history
        WHERE account_id = ?
        ORDER BY close_time DESC
        """,
        (account_id,),
    ).fetchall()

    history: List[Dict] = []
    for row in rows:
        realized = _sum_realized(
            conn,
            account_id,
            row["symbol"],
            row["currency"],
            start_time=row["open_time"],
            end_time=row["close_time"],
        )
        history.append(
            {
                "id": row["id"],
                "symbol": row["symbol"],
                "open_time": row["open_time"],
                "close_time": row["close_time"],
                "realized_pnl": realized,
            }
        )
    return history


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
