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
) -> None:
    conn.execute(
        """
        INSERT INTO trades (account_id, position_id, symbol, exchange, currency, side, qty, price, commission, realized_pnl, trade_time, ibkr_exec_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    row = conn.execute(
        """
        SELECT id, account_id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time
        FROM positions
        WHERE account_id = ? AND symbol = ? AND exchange = ? AND currency = ?
        """,
        (account_id, symbol, exchange, currency),
    ).fetchone()

    if row is None:
        open_time = trade_time_bj
        total_cost = trade_qty_signed * price + commission
        avg_cost = total_cost / trade_qty_signed if trade_qty_signed else 0.0
        conn.execute(
            """
            INSERT INTO positions (account_id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                symbol,
                exchange,
                currency,
                trade_qty_signed,
                avg_cost,
                total_cost,
                0.0,
                open_time,
                _utc_now(),
            ),
        )
        position_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
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
            0.0,
            trade_time_bj,
            ibkr_exec_id,
        )
        conn.commit()
        return {
            "symbol": symbol,
            "exchange": exchange,
            "currency": currency,
            "qty": trade_qty_signed,
            "avg_cost": avg_cost,
            "total_cost": total_cost,
            "realized_trade": 0.0,
            "realized_total": 0.0,
        }

    pos_qty = float(row["qty"])
    avg_cost = float(row["avg_cost"])
    realized_pnl = float(row["realized_pnl"])
    position_id = int(row["id"])
    direction = _position_direction(pos_qty)

    if direction == 0 or direction == _position_direction(trade_qty_signed):
        total_cost = float(row["total_cost"]) + trade_qty_signed * price + commission
        pos_qty += trade_qty_signed
        avg_cost = total_cost / pos_qty if pos_qty else 0.0
        conn.execute(
            """
            UPDATE positions
            SET qty = ?, avg_cost = ?, total_cost = ?, realized_pnl = ?, updated_at = ?
            WHERE id = ?
            """,
            (pos_qty, avg_cost, total_cost, realized_pnl, _utc_now(), position_id),
        )
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
            0.0,
            trade_time_bj,
            ibkr_exec_id,
        )
        conn.commit()
        return {
            "symbol": symbol,
            "exchange": exchange,
            "currency": currency,
            "qty": pos_qty,
            "avg_cost": avg_cost,
            "total_cost": total_cost,
            "realized_trade": 0.0,
            "realized_total": realized_pnl,
        }

    close_qty = min(abs(trade_qty_signed), abs(pos_qty))
    close_ratio = close_qty / abs(trade_qty_signed)
    commission_close = commission * close_ratio
    commission_open = commission - commission_close

    realized_close = _realized_for_close(avg_cost, price, close_qty, direction)
    realized_trade = realized_close - commission_close
    realized_pnl += realized_trade

    remaining_qty = pos_qty + trade_qty_signed

    if remaining_qty == 0:
        conn.execute(
            """
            UPDATE positions
            SET qty = ?, realized_pnl = ?, updated_at = ?
            WHERE id = ?
            """,
            (pos_qty, realized_pnl, _utc_now(), position_id),
        )
        _insert_trade(
            conn,
            account_id,
            position_id,
            symbol,
            exchange,
            currency,
            normalized_side,
            close_qty,
            price,
            commission_close,
            realized_trade,
            trade_time_bj,
            ibkr_exec_id,
        )
        position_row = conn.execute(
            "SELECT * FROM positions WHERE id = ?",
            (position_id,),
        ).fetchone()
        _archive_position(conn, position_row, trade_time_bj)
        conn.commit()
        return {
            "symbol": symbol,
            "exchange": exchange,
            "currency": currency,
            "qty": 0.0,
            "avg_cost": avg_cost,
            "total_cost": avg_cost * pos_qty,
            "realized_trade": realized_trade,
            "realized_total": realized_pnl,
        }

    if _position_direction(remaining_qty) == direction:
        total_cost = avg_cost * remaining_qty
        conn.execute(
            """
            UPDATE positions
            SET qty = ?, avg_cost = ?, total_cost = ?, realized_pnl = ?, updated_at = ?
            WHERE id = ?
            """,
            (remaining_qty, avg_cost, total_cost, realized_pnl, _utc_now(), position_id),
        )
        _insert_trade(
            conn,
            account_id,
            position_id,
            symbol,
            exchange,
            currency,
            normalized_side,
            close_qty,
            price,
            commission_close,
            realized_trade,
            trade_time_bj,
            ibkr_exec_id,
        )
        conn.commit()
        return {
            "symbol": symbol,
            "exchange": exchange,
            "currency": currency,
            "qty": remaining_qty,
            "avg_cost": avg_cost,
            "total_cost": total_cost,
            "realized_trade": realized_trade,
            "realized_total": realized_pnl,
        }

    # Flip direction
    conn.execute(
        """
        UPDATE positions
        SET qty = ?, realized_pnl = ?, updated_at = ?
        WHERE id = ?
        """,
        (pos_qty, realized_pnl, _utc_now(), position_id),
    )
    _insert_trade(
        conn,
        account_id,
        position_id,
        symbol,
        exchange,
        currency,
        normalized_side,
        close_qty,
        price,
        commission_close,
        realized_trade,
        trade_time_bj,
        f"{ibkr_exec_id}-close" if ibkr_exec_id else None,
    )
    position_row = conn.execute(
        "SELECT * FROM positions WHERE id = ?",
        (position_id,),
    ).fetchone()
    _archive_position(conn, position_row, trade_time_bj)

    open_qty = remaining_qty
    open_total_cost = open_qty * price + commission_open
    open_avg_cost = open_total_cost / open_qty if open_qty else 0.0
    conn.execute(
        """
        INSERT INTO positions (account_id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            symbol,
            exchange,
            currency,
            open_qty,
            open_avg_cost,
            open_total_cost,
            0.0,
            trade_time_bj,
            _utc_now(),
        ),
    )
    new_position_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    _insert_trade(
        conn,
        account_id,
        new_position_id,
        symbol,
        exchange,
        currency,
        normalized_side,
        abs(open_qty),
        price,
        commission_open,
        0.0,
        trade_time_bj,
        f"{ibkr_exec_id}-open" if ibkr_exec_id else None,
    )

    conn.commit()

    return {
        "symbol": symbol,
        "exchange": exchange,
        "currency": currency,
        "qty": open_qty,
        "avg_cost": open_avg_cost,
        "total_cost": open_total_cost,
        "realized_trade": realized_trade,
        "realized_total": realized_pnl,
    }
