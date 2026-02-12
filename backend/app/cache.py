from __future__ import annotations

import datetime as dt
import threading
from typing import Any

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
    params: list[Any] = [account_id, symbol, currency]
    if start_time:
        query += " AND trade_time >= %s"
        params.append(start_time)
    if end_time:
        query += " AND trade_time <= %s"
        params.append(end_time)
    row = conn.execute(query, params).fetchone()
    return float(row["total"]) if row else 0.0


class CacheStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._initialized = False
        self.account_id: int | None = None
        self.base_currency: str | None = None
        self.last_update: str | None = None
        self.realized_total: float = 0.0
        self.positions_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.positions_by_id: dict[int, tuple[str, str, str]] = {}
        self.history_by_id: dict[int, dict[str, Any]] = {}
        self.con_id_to_key: dict[int, tuple[str, str, str]] = {}
        self.account_summary: dict[str, Any] = {}
        self.daily_pnl_by_date: dict[str, float] = {}
        self.daily_pnl_series: list[dict[str, Any]] = []
        self.current_trade_date: str | None = None
        self.pending_daily_pnl_payload: dict[str, Any] | None = None
        self.exec_realized_by_id: dict[str, tuple[tuple[str, str, str], float]] = {}
        self.dirty_account_summary_fields: set[str] = set()
        self.dirty_daily_pnl = False

    def is_initialized(self) -> bool:
        with self._lock:
            return self._initialized

    def set_account(self, account_id: int, base_currency: str) -> None:
        with self._lock:
            if self.account_id is None:
                self.account_id = account_id
            if self.base_currency is None:
                self.base_currency = base_currency

    def load_from_db(self, conn: psycopg.Connection, account_id: int, base_currency: str) -> None:
        realized_row = conn.execute(
            """
            SELECT COALESCE(SUM(realized_pnl), 0) AS total
            FROM trades
            WHERE account_id = %s
            """,
            (account_id,),
        ).fetchone()
        realized_total = float(realized_row["total"]) if realized_row else 0.0
        positions = conn.execute(
            """
            SELECT id, symbol, exchange, currency, qty, avg_cost, realized_pnl, unrealized_pnl, daily_pnl,
                   open_time, con_id
            FROM positions
            WHERE account_id = %s
            ORDER BY symbol
            """,
            (account_id,),
        ).fetchall()

        history = conn.execute(
            """
            SELECT id, symbol, exchange, currency, open_time, close_time, realized_pnl
            FROM positions_history
            WHERE account_id = %s
            ORDER BY close_time DESC
            """,
            (account_id,),
        ).fetchall()

        summary_row = conn.execute(
            """
            SELECT net_liquidation, total_cash_value, available_funds, excess_liquidity,
                   init_margin_req, maint_margin_req, gross_position_value, short_market_value, updated_at
            FROM account_summary
            WHERE account_id = %s
            """,
            (account_id,),
        ).fetchone()

        daily_rows = conn.execute(
            """
            SELECT trade_date, daily_pnl
            FROM account_daily_pnl
            WHERE account_id = %s
            ORDER BY trade_date
            """,
            (account_id,),
        ).fetchall()

        with self._lock:
            self.account_id = account_id
            self.base_currency = base_currency
            self.realized_total = realized_total
            self.positions_by_key.clear()
            self.positions_by_id.clear()
            self.history_by_id.clear()
            self.con_id_to_key.clear()

            for row in positions:
                symbol = row["symbol"]
                exchange = row["exchange"] or ""
                currency = row["currency"]
                open_time = row["open_time"]
                realized = float(row["realized_pnl"])
                unrealized = float(row["unrealized_pnl"])
                daily = float(row["daily_pnl"])
                total = realized + unrealized
                key = (symbol, exchange, currency)
                position_id = int(row["id"])
                self.positions_by_key[key] = {
                    "id": position_id,
                    "symbol": symbol,
                    "exchange": exchange,
                    "currency": currency,
                    "qty": float(row["qty"]),
                    "avg_cost": float(row["avg_cost"]),
                    "unrealized_pnl": unrealized,
                    "daily_pnl": daily,
                    "realized_pnl": realized,
                    "total_pnl": total,
                    "open_time": open_time,
                    "con_id": row["con_id"],
                }
                self.positions_by_id[position_id] = key
                if row["con_id"] is not None:
                    self.con_id_to_key[int(row["con_id"])] = key

            for row in history:
                symbol = row["symbol"]
                exchange = row["exchange"] or ""
                currency = row["currency"]
                open_time = row["open_time"]
                close_time = row["close_time"]
                realized = float(row["realized_pnl"])
                self.history_by_id[int(row["id"])] = {
                    "id": int(row["id"]),
                    "symbol": symbol,
                    "exchange": exchange,
                    "currency": currency,
                    "open_time": open_time,
                    "close_time": close_time,
                    "realized_pnl": realized,
                }

            if summary_row:
                self.account_summary = {
                    "account_id": account_id,
                    "base_currency": base_currency,
                    "net_liquidation": summary_row["net_liquidation"],
                    "total_cash_value": summary_row["total_cash_value"],
                    "available_funds": summary_row["available_funds"],
                    "excess_liquidity": summary_row["excess_liquidity"],
                    "init_margin_req": summary_row["init_margin_req"],
                    "maint_margin_req": summary_row["maint_margin_req"],
                    "gross_position_value": summary_row["gross_position_value"],
                    "short_market_value": summary_row["short_market_value"],
                    "as_of": summary_row["updated_at"],
                }
            else:
                self.account_summary = {}

            self.daily_pnl_by_date = {
                row["trade_date"]: float(row["daily_pnl"]) for row in daily_rows
            }
            self._rebuild_daily_series_locked()
            if self.daily_pnl_by_date:
                self.current_trade_date = max(self.daily_pnl_by_date.keys())
            else:
                self.current_trade_date = None
            self.pending_daily_pnl_payload = None
            self.dirty_daily_pnl = False

            self._initialized = True

    def mark_update(self) -> None:
        now = _utc_now()
        with self._lock:
            self.last_update = now
            self._initialized = True

    def update_position(
        self,
        *,
        position_id: int | None,
        symbol: str,
        exchange: str,
        currency: str,
        qty: float,
        avg_cost: float,
        open_time: str,
        con_id: int | None,
    ) -> None:
        key = (symbol, exchange, currency)
        with self._lock:
            existing = self.positions_by_key.get(key)
            unrealized = existing.get("unrealized_pnl", 0.0) if existing else 0.0
            daily = existing.get("daily_pnl", 0.0) if existing else 0.0
            realized = existing.get("realized_pnl", 0.0) if existing else 0.0
            total = realized + unrealized
            if position_id is None and existing:
                position_id = existing.get("id")
            if position_id is not None:
                self.positions_by_id[int(position_id)] = key
            if con_id is not None:
                self.con_id_to_key[int(con_id)] = key
            self.positions_by_key[key] = {
                "id": position_id,
                "symbol": symbol,
                "exchange": exchange,
                "currency": currency,
                "qty": qty,
                "avg_cost": avg_cost,
                "unrealized_pnl": unrealized,
                "daily_pnl": daily,
                "realized_pnl": realized,
                "total_pnl": total,
                "open_time": open_time,
                "con_id": con_id,
            }
            self._initialized = True
            self.last_update = _utc_now()

    def remove_position(self, symbol: str, exchange: str, currency: str) -> None:
        key = (symbol, exchange, currency)
        with self._lock:
            existing = self.positions_by_key.pop(key, None)
            if existing and existing.get("id") is not None:
                self.positions_by_id.pop(int(existing["id"]), None)
            if existing and existing.get("con_id") is not None:
                self.con_id_to_key.pop(int(existing["con_id"]), None)
            self._initialized = True
            self.last_update = _utc_now()

    def add_history(
        self,
        *,
        position_id: int,
        symbol: str,
        exchange: str,
        currency: str,
        open_time: str,
        close_time: str,
        realized_pnl: float,
    ) -> None:
        with self._lock:
            self.history_by_id[int(position_id)] = {
                "id": int(position_id),
                "symbol": symbol,
                "exchange": exchange,
                "currency": currency,
                "open_time": open_time,
                "close_time": close_time,
                "realized_pnl": realized_pnl,
            }
            self._initialized = True
            self.last_update = _utc_now()

    def update_history_realized(
        self, position_id: int, close_time: str, realized_pnl: float
    ) -> None:
        with self._lock:
            entry = self.history_by_id.get(int(position_id))
            if not entry:
                return
            entry["close_time"] = close_time
            entry["realized_pnl"] = realized_pnl
            self._initialized = True
            self.last_update = _utc_now()

    def update_open_time(self, symbol: str, currency: str, trade_time: str) -> None:
        with self._lock:
            for key, entry in self.positions_by_key.items():
                if key[0] == symbol and key[2] == currency:
                    entry["open_time"] = trade_time
            self._initialized = True
            self.last_update = _utc_now()

    def update_position_pnl_by_con_id(
        self, con_id: int, unrealized_pnl: float, daily_pnl: float | None
    ) -> None:
        with self._lock:
            key = self.con_id_to_key.get(int(con_id))
            if not key:
                return
            entry = self.positions_by_key.get(key)
            if not entry:
                return
            entry["unrealized_pnl"] = unrealized_pnl
            if daily_pnl is not None:
                entry["daily_pnl"] = daily_pnl
            entry["total_pnl"] = entry.get("realized_pnl", 0.0) + entry.get(
                "unrealized_pnl", 0.0
            )
            self._initialized = True
            self.last_update = _utc_now()

    def apply_realized_delta(
        self, position_key: tuple[str, str, str], realized_delta: float
    ) -> None:
        with self._lock:
            entry = self.positions_by_key.get(position_key)
            if not entry:
                return
            entry["realized_pnl"] = entry.get("realized_pnl", 0.0) + realized_delta
            entry["total_pnl"] = entry.get("realized_pnl", 0.0) + entry.get(
                "unrealized_pnl", 0.0
            )
            self._initialized = True
            self.last_update = _utc_now()

    def update_daily_pnl(self, trade_date: str, daily_pnl: float) -> None:
        with self._lock:
            previous_date = self.current_trade_date
            self.daily_pnl_by_date[trade_date] = daily_pnl
            self._rebuild_daily_series_locked()
            if previous_date and previous_date != trade_date:
                payload = self._daily_payload_for_date_locked(previous_date)
                if payload:
                    self.pending_daily_pnl_payload = payload
                    self.dirty_daily_pnl = True
            self.current_trade_date = trade_date
            self._initialized = True
            self.last_update = _utc_now()

    def update_account_summary(self, field: str, value: float) -> None:
        with self._lock:
            self.account_summary[field] = value
            self.account_summary["account_id"] = self.account_id
            self.account_summary["base_currency"] = self.base_currency
            self.account_summary["as_of"] = _utc_now()
            self.dirty_account_summary_fields.add(field)
            self._initialized = True
            self.last_update = _utc_now()

    def record_exec_realized(
        self, exec_id: str, position_key: tuple[str, str, str], realized: float
    ) -> None:
        with self._lock:
            previous = self.exec_realized_by_id.get(exec_id)
            if previous:
                _, last_realized = previous
                delta = realized - last_realized
            else:
                delta = realized
            self.exec_realized_by_id[exec_id] = (position_key, realized)
            if delta:
                self.realized_total += delta
        if delta:
            self.apply_realized_delta(position_key, delta)

    def get_position_realized(self, position_key: tuple[str, str, str]) -> float | None:
        with self._lock:
            entry = self.positions_by_key.get(position_key)
            if not entry:
                return None
            return float(entry.get("realized_pnl", 0.0))

    def snapshot_positions(self) -> list[dict[str, Any]]:
        with self._lock:
            positions = list(self.positions_by_key.values())
        positions.sort(key=lambda item: item.get("symbol") or "")
        return [
            {
                "id": item.get("id"),
                "symbol": item.get("symbol"),
                "qty": float(item.get("qty", 0.0)),
                "avg_cost": float(item.get("avg_cost", 0.0)),
                "realized_pnl": float(item.get("realized_pnl", 0.0)),
                "unrealized_pnl": float(item.get("unrealized_pnl", 0.0)),
                "total_pnl": float(item.get("total_pnl", 0.0)),
                "daily_pnl": float(item.get("daily_pnl", 0.0)),
                "open_time": _format_bj_time(item.get("open_time")),
            }
            for item in positions
        ]

    def snapshot_history(self) -> list[dict[str, Any]]:
        with self._lock:
            history = list(self.history_by_id.values())
        history.sort(key=lambda item: item.get("close_time") or "", reverse=True)
        return [
            {
                "id": item.get("id"),
                "symbol": item.get("symbol"),
                "open_time": _format_bj_time(item.get("open_time")),
                "close_time": _format_bj_time(item.get("close_time")),
                "realized_pnl": float(item.get("realized_pnl", 0.0)),
            }
            for item in history
        ]

    def snapshot_account_pnl(self) -> dict[str, Any]:
        with self._lock:
            positions = list(self.positions_by_key.values())
            realized_total = self.realized_total
            daily_value = 0.0
            if self.daily_pnl_by_date:
                latest_date = max(self.daily_pnl_by_date.keys())
                daily_value = float(self.daily_pnl_by_date[latest_date])
            base_currency = self.base_currency
            account_id = self.account_id
            as_of = self.last_update or _utc_now()
        unrealized_total = sum(item.get("unrealized_pnl", 0.0) for item in positions)
        total_value = realized_total + unrealized_total
        return {
            "account_id": account_id,
            "base_currency": base_currency,
            "realized_pnl": realized_total,
            "unrealized_pnl": unrealized_total,
            "daily_pnl": daily_value,
            "total_pnl": total_value,
            "as_of": as_of,
        }

    def snapshot_account_summary(self) -> dict[str, Any]:
        with self._lock:
            summary = dict(self.account_summary) if self.account_summary else {}
            account_id = self.account_id
            base_currency = self.base_currency
        if not summary:
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
        summary.setdefault("account_id", account_id)
        summary.setdefault("base_currency", base_currency)
        summary.setdefault("as_of", _utc_now())
        return summary

    def snapshot_daily_pnl(self) -> list[dict[str, Any]]:
        with self._lock:
            series = list(self.daily_pnl_series)
        return [
            {
                "trade_date": item["trade_date"],
                "daily_pnl": float(item["daily_pnl"]),
                "cumulative_pnl": float(item["cumulative_pnl"]),
            }
            for item in series
        ]

    def snapshot_trade_cumulative(self) -> list[dict[str, Any]]:
        with self._lock:
            series = list(self.daily_pnl_series)
        return [
            {
                "trade_date": item["trade_date"],
                "cumulative_pnl": float(item["cumulative_pnl"]),
                "daily_pnl": float(item["daily_pnl"]),
            }
            for item in series
        ]

    def collect_flush_payload(
        self,
    ) -> tuple[dict[str, Any] | None, set[str], dict[str, Any] | None]:
        with self._lock:
            summary_fields = set(self.dirty_account_summary_fields)
            account_summary = dict(self.account_summary) if summary_fields else None
            daily_payload = None
            if self.dirty_daily_pnl and self.pending_daily_pnl_payload:
                daily_payload = dict(self.pending_daily_pnl_payload)
        return account_summary, summary_fields, daily_payload

    def clear_dirty(
        self,
        account_summary_fields: set[str] | None = None,
        daily_pnl: bool = False,
    ) -> None:
        with self._lock:
            if account_summary_fields:
                self.dirty_account_summary_fields -= set(account_summary_fields)
            if daily_pnl:
                self.dirty_daily_pnl = False
                self.pending_daily_pnl_payload = None

    def _rebuild_daily_series_locked(self) -> None:
        dates = sorted(self.daily_pnl_by_date.keys())
        cumulative = 0.0
        series: list[dict[str, Any]] = []
        for trade_date in dates:
            daily_value = float(self.daily_pnl_by_date[trade_date])
            cumulative += daily_value
            series.append(
                {
                    "trade_date": trade_date,
                    "daily_pnl": daily_value,
                    "cumulative_pnl": cumulative,
                }
            )
        self.daily_pnl_series = series

    def _current_daily_payload_locked(self) -> dict[str, Any] | None:
        if not self.daily_pnl_series:
            return None
        last = self.daily_pnl_series[-1]
        return {
            "trade_date": last["trade_date"],
            "daily_pnl": float(last["daily_pnl"]),
            "cumulative_pnl": float(last["cumulative_pnl"]),
        }

    def _daily_payload_for_date_locked(self, trade_date: str) -> dict[str, Any] | None:
        for entry in self.daily_pnl_series:
            if entry["trade_date"] == trade_date:
                return {
                    "trade_date": entry["trade_date"],
                    "daily_pnl": float(entry["daily_pnl"]),
                    "cumulative_pnl": float(entry["cumulative_pnl"]),
                }
        return None
