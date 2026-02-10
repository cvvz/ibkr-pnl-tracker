from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Dict

BEIJING_TZ = dt.timezone(dt.timedelta(hours=8))


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _to_beijing(iso_time: str | None) -> str:
    if not iso_time:
        return dt.datetime.now(tz=BEIJING_TZ).isoformat()
    try:
        parsed = dt.datetime.fromisoformat(iso_time)
    except ValueError:
        return dt.datetime.now(tz=BEIJING_TZ).isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(BEIJING_TZ).isoformat()


def _position_direction(qty: float) -> int:
    if qty > 0:
        return 1
    if qty < 0:
        return -1
    return 0


def _realized_for_close(avg_cost: float, price: float, close_qty: float, direction: int) -> float:
    if direction >= 0:
        return (price - avg_cost) * close_qty
    return (avg_cost - price) * close_qty


def _select_position(
    conn: sqlite3.Connection,
    account_id: int,
    symbol: str,
    exchange: str,
    currency: str,
) -> sqlite3.Row | None:
    exchange = exchange or ""
    row = conn.execute(
        """
        SELECT id, account_id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time
        FROM positions
        WHERE account_id = ? AND symbol = ? AND exchange = ? AND currency = ?
        """,
        (account_id, symbol, exchange, currency),
    ).fetchone()
    if row:
        return row
    rows = conn.execute(
        """
        SELECT id, account_id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time
        FROM positions
        WHERE account_id = ? AND symbol = ? AND currency = ?
        """,
        (account_id, symbol, currency),
    ).fetchall()
    if not rows:
        return None
    for candidate in rows:
        if candidate["exchange"]:
            return candidate
    return rows[0]


def _insert_trade(
    conn: sqlite3.Connection,
    account_id: int,
    position_id: int | None,
    symbol: str,
    exchange: str,
    currency: str,
    side: str,
    qty: float,
    price: float,
    commission: float,
    realized_pnl: float,
    trade_time: str,
    ibkr_exec_id: str | None,
    perm_id: int | None,
) -> None:
    conn.execute(
        """
        INSERT INTO trades (
            account_id,
            position_id,
            symbol,
            exchange,
            currency,
            side,
            qty,
            price,
            commission,
            realized_pnl,
            trade_time,
            ibkr_exec_id,
            perm_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            position_id,
            symbol,
            exchange,
            currency,
            side,
            qty,
            price,
            commission,
            realized_pnl,
            trade_time,
            ibkr_exec_id,
            perm_id,
        ),
    )


def _archive_position(
    conn: sqlite3.Connection,
    position_row: sqlite3.Row,
    close_time: str,
) -> None:
    open_time = position_row["open_time"] or close_time
    conn.execute(
        """
        INSERT INTO positions_history
            (id, account_id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time, close_time, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            position_row["id"],
            position_row["account_id"],
            position_row["symbol"],
            position_row["exchange"],
            position_row["currency"],
            position_row["qty"],
            position_row["avg_cost"],
            position_row["total_cost"],
            position_row["realized_pnl"],
            open_time,
            close_time,
            _utc_now(),
        ),
    )
    conn.execute("DELETE FROM positions WHERE id = ?", (position_row["id"],))


def apply_trade(
    conn: sqlite3.Connection,
    account_id: int,
    symbol: str,
    exchange: str | None,
    currency: str,
    side: str,
    qty: float,
    price: float,
    commission: float,
    trade_time: str,
    ibkr_exec_id: str | None,
    perm_id: int | None = None,
) -> Dict:
    normalized_side = side.lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")

    exchange = exchange or ""
    qty = float(qty)
    price = float(price)
    commission = float(commission)
    trade_qty_signed = qty if normalized_side == "buy" else -qty
    trade_time_bj = _to_beijing(trade_time)

    row = _select_position(conn, account_id, symbol, exchange, currency)
    position_id = int(row["id"]) if row else None
    pos_qty = float(row["qty"]) if row else 0.0
    avg_cost = float(row["avg_cost"]) if row else price
    direction = _position_direction(pos_qty)
    trade_direction = _position_direction(trade_qty_signed)

    if row and direction != 0 and trade_direction != 0 and direction != trade_direction:
        close_qty = min(abs(trade_qty_signed), abs(pos_qty))
        realized_close = _realized_for_close(avg_cost, price, close_qty, direction)
        realized_trade = realized_close - commission
    else:
        realized_trade = -commission

    _insert_trade(
        conn,
        account_id,
        position_id,
        symbol,
        exchange,
        currency,
        normalized_side,
        qty,
        price,
        commission,
        realized_trade,
        trade_time_bj,
        ibkr_exec_id,
        perm_id,
    )
    if position_id is not None:
        conn.execute(
            """
            UPDATE positions
            SET realized_pnl = realized_pnl + ?, updated_at = ?
            WHERE id = ?
            """,
            (realized_trade, _utc_now(), position_id),
        )
    conn.commit()
    return {
        "symbol": symbol,
        "exchange": exchange,
        "currency": currency,
        "qty": pos_qty,
        "avg_cost": avg_cost,
        "total_cost": float(row["total_cost"]) if row else 0.0,
        "realized_trade": realized_trade,
        "realized_total": float(row["realized_pnl"]) + realized_trade if row else realized_trade,
    }
