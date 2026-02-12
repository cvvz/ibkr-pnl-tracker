from __future__ import annotations

import datetime as dt
from typing import Dict, List

import psycopg

_BEIJING_TZ = dt.timezone(dt.timedelta(hours=8))


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _format_bj_time(value: str | None) -> str | None:
    if not value:
        return value
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return parsed.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _sum_realized(
    conn: psycopg.Connection,
    account_id: int,
    symbol: str,
    currency: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> float:
    query = """
        SELECT COALESCE(SUM(realized_pnl), 0) AS total
        FROM trades
        WHERE account_id = %s AND symbol = %s AND currency = %s
    """
    params: List[object] = [account_id, symbol, currency]
    if start_time:
        query += " AND trade_time >= %s"
        params.append(start_time)
    if end_time:
        query += " AND trade_time <= %s"
        params.append(end_time)
    row = conn.execute(query, params).fetchone()
    return float(row["total"]) if row else 0.0


def get_positions(conn: psycopg.Connection, account_id: int, base_currency: str) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT id, symbol, exchange, currency, qty, avg_cost, unrealized_pnl, daily_pnl, open_time
        FROM positions
        WHERE account_id = %s
        ORDER BY symbol
        """,
        (account_id,),
    ).fetchall()

    positions: List[Dict] = []
    for row in rows:
        open_time = row["open_time"]
        realized = _sum_realized(
            conn,
            account_id,
            row["symbol"],
            row["currency"],
            start_time=open_time,
        )
        unrealized = float(row["unrealized_pnl"])
        daily = float(row["daily_pnl"])
        positions.append(
            {
                "id": row["id"],
                "symbol": row["symbol"],
                "qty": float(row["qty"]),
                "avg_cost": float(row["avg_cost"]),
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "total_pnl": realized + unrealized,
                "daily_pnl": daily,
                "open_time": _format_bj_time(open_time),
            }
        )
    return positions


def get_history_positions(conn: psycopg.Connection, account_id: int, base_currency: str) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT id, symbol, exchange, currency, open_time, close_time
        FROM positions_history
        WHERE account_id = %s
        ORDER BY close_time DESC
        """,
        (account_id,),
    ).fetchall()

    history: List[Dict] = []
    for row in rows:
        open_time = row["open_time"]
        close_time = row["close_time"]
        realized = _sum_realized(
            conn,
            account_id,
            row["symbol"],
            row["currency"],
            start_time=open_time,
            end_time=close_time,
        )
        history.append(
            {
                "id": row["id"],
                "symbol": row["symbol"],
                "open_time": _format_bj_time(open_time),
                "close_time": _format_bj_time(close_time),
                "realized_pnl": realized,
            }
        )
    return history


def get_account_summary(conn: psycopg.Connection, account_id: int, base_currency: str) -> Dict:
    row = conn.execute(
        """
        SELECT realized_pnl, unrealized_pnl, daily_pnl, total_pnl, updated_at
        FROM account_pnl
        WHERE account_id = %s
        """,
        (account_id,),
    ).fetchone()
    if row:
        return {
            "account_id": account_id,
            "base_currency": base_currency,
            "realized_pnl": float(row["realized_pnl"]),
            "unrealized_pnl": float(row["unrealized_pnl"]),
            "daily_pnl": float(row["daily_pnl"]),
            "total_pnl": float(row["total_pnl"]),
            "as_of": row["updated_at"],
        }

    return {
        "account_id": account_id,
        "base_currency": base_currency,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "daily_pnl": 0.0,
        "total_pnl": 0.0,
        "as_of": _utc_now(),
    }


def get_account_daily_pnl(conn: psycopg.Connection, account_id: int) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT trade_date, daily_pnl, cumulative_pnl
        FROM account_daily_pnl
        WHERE account_id = %s
        ORDER BY trade_date
        """,
        (account_id,),
    ).fetchall()
    return [
        {
            "trade_date": row["trade_date"],
            "daily_pnl": float(row["daily_pnl"]),
            "cumulative_pnl": float(row["cumulative_pnl"]),
        }
        for row in rows
    ]


def get_trade_cumulative(conn: psycopg.Connection, account_id: int) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT trade_date, daily_pnl
        FROM account_daily_pnl
        WHERE account_id = %s
        ORDER BY trade_date
        """,
        (account_id,),
    ).fetchall()

    cumulative = 0.0
    series: List[Dict] = []
    for row in rows:
        daily_value = float(row["daily_pnl"])
        cumulative += daily_value
        series.append(
            {
                "trade_date": row["trade_date"],
                "cumulative_pnl": cumulative,
                "daily_pnl": daily_value,
            }
        )

    return series


def get_account_snapshot(conn: psycopg.Connection, account_id: int, base_currency: str) -> Dict:
    row = conn.execute(
        """
        SELECT net_liquidation, total_cash_value, available_funds, excess_liquidity,
               init_margin_req, maint_margin_req, gross_position_value, short_market_value, updated_at
        FROM account_summary
        WHERE account_id = %s
        """,
        (account_id,),
    ).fetchone()
    if not row:
        return {
            "account_id": account_id,
            "base_currency": base_currency,
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

    return {
        "account_id": account_id,
        "base_currency": base_currency,
        "net_liquidation": float(row["net_liquidation"]) if row["net_liquidation"] is not None else None,
        "total_cash_value": float(row["total_cash_value"]) if row["total_cash_value"] is not None else None,
        "available_funds": float(row["available_funds"]) if row["available_funds"] is not None else None,
        "excess_liquidity": float(row["excess_liquidity"]) if row["excess_liquidity"] is not None else None,
        "init_margin_req": float(row["init_margin_req"]) if row["init_margin_req"] is not None else None,
        "maint_margin_req": float(row["maint_margin_req"]) if row["maint_margin_req"] is not None else None,
        "gross_position_value": float(row["gross_position_value"]) if row["gross_position_value"] is not None else None,
        "short_market_value": float(row["short_market_value"]) if row["short_market_value"] is not None else None,
        "as_of": row["updated_at"],
    }
