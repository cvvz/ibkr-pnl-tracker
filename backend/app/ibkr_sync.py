from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Optional
from zoneinfo import ZoneInfo

import psycopg
from ib_insync import IB, LimitOrder, MarketOrder, Position, Stock

from .config import Settings
from .cache import CacheStore
from .db import get_connection, upsert_account

logger = logging.getLogger("uvicorn.error")


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


_NON_PRIMARY_EXCHANGES = {"IBKRATS", "OVERNIGHT"}
_EASTERN_TZ = ZoneInfo("America/New_York")
_ACCOUNT_SUMMARY_TAGS = {
    "NetLiquidation": "net_liquidation",
    "TotalCashValue": "total_cash_value",
    "AvailableFunds": "available_funds",
    "ExcessLiquidity": "excess_liquidity",
    "InitMarginReq": "init_margin_req",
    "MaintMarginReq": "maint_margin_req",
    "GrossPositionValue": "gross_position_value",
    "ShortMarketValue": "short_market_value",
}


def _trade_date_et(now: dt.datetime | None = None) -> str:
    current = now or dt.datetime.now(tz=_EASTERN_TZ)
    return current.date().isoformat()


def _normalize_side(side: str) -> str:
    normalized = side.strip().lower()
    if normalized in {"bot", "buy"}:
        return "buy"
    if normalized in {"sld", "sell"}:
        return "sell"
    return normalized


def _resolve_trade_exchange(
    conn: psycopg.Connection,
    account_id: int,
    symbol: str,
    currency: str,
    exchange: str,
) -> str:
    exchange = exchange or ""
    rows = conn.execute(
        """
        SELECT exchange
        FROM positions
        WHERE account_id = %s AND symbol = %s AND currency = %s
        """,
        (account_id, symbol, currency),
    ).fetchall()
    if not rows:
        return exchange
    for row in rows:
        if row["exchange"] == exchange:
            return exchange
    for row in rows:
        if row["exchange"] and row["exchange"] not in _NON_PRIMARY_EXCHANGES:
            return row["exchange"]
    return rows[0]["exchange"]


def _trade_time(value: dt.datetime | None) -> str:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.isoformat()
    return _utc_now()


def _get_last_close_time(
    conn: psycopg.Connection,
    account_id: int,
    symbol: str,
    currency: str,
) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(close_time) AS last_close
        FROM positions_history
        WHERE account_id = %s AND symbol = %s AND currency = %s
        """,
        (account_id, symbol, currency),
    ).fetchone()
    return row["last_close"] if row and row["last_close"] else None


def _get_first_trade_time(
    conn: psycopg.Connection,
    account_id: int,
    symbol: str,
    currency: str,
    after_time: str | None = None,
) -> str | None:
    query = """
        SELECT MIN(trade_time) AS first_trade
        FROM trades
        WHERE account_id = %s AND symbol = %s AND currency = %s
    """
    params: list[object] = [account_id, symbol, currency]
    if after_time:
        query += " AND trade_time > %s"
        params.append(after_time)
    row = conn.execute(query, params).fetchone()
    return row["first_trade"] if row and row["first_trade"] else None


def _get_last_trade_time(
    conn: psycopg.Connection,
    account_id: int,
    symbol: str,
    currency: str,
) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(trade_time) AS last_trade
        FROM trades
        WHERE account_id = %s AND symbol = %s AND currency = %s
        """,
        (account_id, symbol, currency),
    ).fetchone()
    return row["last_trade"] if row and row["last_trade"] else None


def _sum_realized(
    conn: psycopg.Connection,
    account_id: int,
    symbol: str,
    currency: str,
    start_time: str,
    end_time: str,
) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(realized_pnl), 0) AS total
        FROM trades
        WHERE account_id = %s AND symbol = %s AND currency = %s
          AND trade_time >= %s AND trade_time <= %s
        """,
        (account_id, symbol, currency, start_time, end_time),
    ).fetchone()
    return float(row["total"]) if row else 0.0


@dataclass
class SyncStatus:
    running: bool
    connected: bool = False
    error: Optional[str] = None
    started_at: Optional[str] = None
    last_update: Optional[str] = None
    last_connected_at: Optional[str] = None
    last_disconnected_at: Optional[str] = None
    ibkr_connected: Optional[bool] = None
    ibkr_last_connected_at: Optional[str] = None
    ibkr_last_disconnected_at: Optional[str] = None


@dataclass
class OrderPayload:
    symbol: str
    qty: float
    side: str
    order_type: str
    price: float | None
    exchange: str | None
    currency: str | None
    tif: str | None
    account: str | None


@dataclass
class OrderJob:
    request_id: str
    payload: OrderPayload


@dataclass
class OrderResult:
    success: bool
    result: dict | None = None
    error: str | None = None
    request_id: str | None = None


class IBKRSyncManager:
    def __init__(self, settings: Settings, cache: CacheStore | None = None) -> None:
        self.settings = settings
        self._cache = cache or CacheStore()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._status = SyncStatus(running=False)
        self._order_queue: Queue[OrderJob] = Queue(maxsize=self.settings.ib_order_queue_max)
        self._order_waiters: dict[str, tuple[threading.Event, OrderResult]] = {}
        self._order_lock = threading.Lock()

    def status(self) -> SyncStatus:
        return self._status

    def start(self) -> SyncStatus:
        if self._thread and self._thread.is_alive():
            return self._status
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self._status

    def stop(self) -> SyncStatus:
        self._stop_event.set()
        return self._status

    def enqueue_order(
        self,
        payload: OrderPayload,
        request_id: str | None = None,
        timeout: float = 8.0,
    ) -> OrderResult:
        if not self._status.connected:
            return OrderResult(success=False, error="IB Gateway disconnected")
        request_id = request_id or uuid.uuid4().hex
        event = threading.Event()
        result = OrderResult(success=False, error="Order queued", request_id=request_id)
        with self._order_lock:
            self._order_waiters[request_id] = (event, result)
        try:
            self._order_queue.put_nowait(OrderJob(request_id=request_id, payload=payload))
        except Full:
            with self._order_lock:
                self._order_waiters.pop(request_id, None)
            return OrderResult(success=False, error="Order queue full", request_id=request_id)
        logger.info(
            "Order queued request_id=%s symbol=%s side=%s qty=%s type=%s price=%s",
            request_id,
            payload.symbol,
            payload.side,
            payload.qty,
            payload.order_type,
            payload.price,
        )
        if event.wait(timeout):
            return result
        return OrderResult(
            success=True,
            result={"status": "queued", "request_id": request_id},
            request_id=request_id,
        )

    def _run(self) -> None:
        asyncio.set_event_loop(asyncio.new_event_loop())
        self._status = SyncStatus(running=True, started_at=_utc_now())
        backoff = max(1, self.settings.ib_reconnect_min_delay)

        while not self._stop_event.is_set():
            ib = IB()
            conn: psycopg.Connection | None = None
            try:
                ib.connect(
                    self.settings.ib_host,
                    self.settings.ib_port,
                    clientId=self.settings.ib_client_id,
                    readonly=self.settings.ib_readonly,
                )
                self._status.connected = True
                self._status.last_connected_at = _utc_now()
                self._status.ibkr_connected = True
                self._status.ibkr_last_connected_at = _utc_now()
                self._status.error = None
                logger.info("IB connected ok")

                conn = get_connection(self.settings.database_url)
                account = ib.managedAccounts()[0] if ib.managedAccounts() else "LOCAL"
                account_id = upsert_account(conn, account, self.settings.base_currency)
                self._cache.set_account(account_id, self.settings.base_currency)
                if not self._cache.is_initialized():
                    self._cache.load_from_db(conn, account_id, self.settings.base_currency)

                pending_commission_reports: dict[str, tuple[float, float]] = {}
                pnl_req_by_con: dict[int, int] = {}
                con_by_req: dict[int, int] = {}
                account_pnl_req_id: int | None = None
                account_summary_req_id: int | None = None
                last_pnl_single: dict[int, tuple[float | None, float]] = {}
                pending_pnl_single: dict[int, tuple[float, float | None]] = {}

                def ensure_conn() -> psycopg.Connection:
                    nonlocal conn, account_id
                    if conn is None or conn.closed:
                        conn = get_connection(self.settings.database_url)
                        account_id = upsert_account(conn, account, self.settings.base_currency)
                        self._cache.set_account(account_id, self.settings.base_currency)
                    else:
                        try:
                            if conn.info.transaction_status == psycopg.pq.TransactionStatus.INERROR:
                                conn.rollback()
                        except Exception:
                            pass
                    return conn

                def set_order_result(request_id: str, result: OrderResult) -> None:
                    with self._order_lock:
                        waiter = self._order_waiters.pop(request_id, None)
                    if not waiter:
                        return
                    event, ref = waiter
                    ref.success = result.success
                    ref.result = result.result
                    ref.error = result.error
                    ref.request_id = request_id
                    event.set()

                def mark_update() -> None:
                    self._status.last_update = _utc_now()

                def span_start(label: str, extra: str = "") -> float:
                    if extra:
                        logger.debug("Span start %s %s", label, extra)
                    else:
                        logger.debug("Span start %s", label)
                    return time.perf_counter()

                def span_end(label: str, start: float, extra: str = "") -> None:
                    duration = time.perf_counter() - start
                    if extra:
                        logger.debug("Span end %s %.3fs %s", label, duration, extra)
                    else:
                        logger.debug("Span end %s %.3fs", label, duration)

                def coerce_float(value: object) -> float | None:
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        return None
                    if not math.isfinite(number):
                        return None
                    return number

                def update_trade_from_report(exec_id: str, commission: float, realized: float) -> None:
                    span = span_start(
                        "db.update_trade_from_report",
                        f"exec_id={exec_id} commission={commission} realized={realized}",
                    )
                    ensure_conn()
                    row = conn.execute(
                        "SELECT id, symbol, exchange, currency, trade_time FROM trades WHERE ibkr_exec_id = %s",
                        (exec_id,),
                    ).fetchone()
                    if not row:
                        pending_commission_reports[exec_id] = (commission, realized)
                        span_end("db.update_trade_from_report", span, f"exec_id={exec_id} pending")
                        return
                    try:
                        conn.execute(
                            "UPDATE trades SET commission = %s, realized_pnl = %s WHERE id = %s",
                            (commission, realized, row["id"]),
                        )
                        conn.commit()
                        position_key = (
                            row["symbol"],
                            row["exchange"] or "",
                            row["currency"],
                        )
                        self._cache.record_exec_realized(exec_id, position_key, realized)
                        update_position_realized_db(position_key)
                        maybe_update_history_from_trade(
                            row["symbol"],
                            row["exchange"],
                            row["currency"],
                            row["trade_time"],
                            realized,
                        )
                        mark_update()
                    finally:
                        span_end("db.update_trade_from_report", span, f"exec_id={exec_id}")

                def maybe_update_history_from_trade(
                    symbol: str,
                    exchange: str,
                    currency: str,
                    trade_time: str,
                    realized: float,
                ) -> None:
                    if realized == 0.0:
                        return
                    ensure_conn()
                    open_row = conn.execute(
                        """
                        SELECT id
                        FROM positions
                        WHERE account_id = %s AND symbol = %s AND currency = %s
                        """,
                        (account_id, symbol, currency),
                    ).fetchone()
                    if open_row:
                        return
                    history_row = conn.execute(
                        """
                        SELECT id, open_time, close_time
                        FROM positions_history
                        WHERE account_id = %s AND symbol = %s AND currency = %s
                        ORDER BY close_time DESC
                        LIMIT 1
                        """,
                        (account_id, symbol, currency),
                    ).fetchone()
                    if not history_row:
                        return
                    try:
                        trade_dt = dt.datetime.fromisoformat(trade_time)
                    except ValueError:
                        trade_dt = None
                    try:
                        close_dt = dt.datetime.fromisoformat(history_row["close_time"])
                    except ValueError:
                        close_dt = None
                    if trade_dt and close_dt:
                        new_close = trade_time if trade_dt >= close_dt else history_row["close_time"]
                    else:
                        new_close = trade_time
                    realized_total = _sum_realized(
                        conn,
                        account_id,
                        symbol,
                        currency,
                        history_row["open_time"],
                        new_close,
                    )
                    conn.execute(
                        """
                        UPDATE positions_history
                        SET close_time = %s, realized_pnl = %s, updated_at = %s
                        WHERE id = %s
                        """,
                        (new_close, realized_total, _utc_now(), history_row["id"]),
                    )
                    conn.commit()
                    self._cache.update_history_realized(
                        int(history_row["id"]), new_close, realized_total
                    )

                def maybe_update_open_time(
                    symbol: str, currency: str, trade_time: str
                ) -> None:
                    ensure_conn()
                    row = conn.execute(
                        """
                        SELECT id, open_time
                        FROM positions
                        WHERE account_id = %s AND symbol = %s AND currency = %s
                        """,
                        (account_id, symbol, currency),
                    ).fetchone()
                    if not row or not row["open_time"]:
                        return
                    if trade_time < row["open_time"]:
                        conn.execute(
                            "UPDATE positions SET open_time = %s, updated_at = %s WHERE id = %s",
                            (trade_time, _utc_now(), row["id"]),
                        )
                        conn.commit()
                        self._cache.update_open_time(symbol, currency, trade_time)

                def update_position_realized_db(position_key: tuple[str, str, str]) -> None:
                    realized_value = self._cache.get_position_realized(position_key)
                    if realized_value is None:
                        return
                    ensure_conn()
                    symbol, exchange, currency = position_key
                    conn.execute(
                        """
                        UPDATE positions
                        SET realized_pnl = %s, updated_at = %s
                        WHERE account_id = %s AND symbol = %s AND exchange = %s AND currency = %s
                        """,
                        (realized_value, _utc_now(), account_id, symbol, exchange, currency),
                    )
                    conn.commit()

                def update_account_daily_pnl(daily_value: float) -> None:
                    trade_date = _trade_date_et()
                    self._cache.update_daily_pnl(trade_date, daily_value)

                def update_account_summary(tag: str, value: float) -> str | None:
                    column = _ACCOUNT_SUMMARY_TAGS.get(tag)
                    if not column:
                        return None
                    self._cache.update_account_summary(column, value)
                    mark_update()
                    return column

                def insert_trade(
                    symbol: str,
                    exchange: str,
                    currency: str,
                    side: str,
                    qty: float,
                    price: float,
                    commission: float,
                    realized: float,
                    trade_time: str,
                    exec_id: str | None,
                    perm_id: int | None,
                ) -> None:
                    logged = False
                    span = span_start(
                        "db.insert_trade",
                        f"symbol={symbol} exchange={exchange} qty={qty} price={price}",
                    )
                    try:
                        ensure_conn()
                        conn.execute(
                            """
                            INSERT INTO trades
                                (account_id, symbol, exchange, currency, side, qty, price, commission, realized_pnl,
                                 trade_time, ibkr_exec_id, perm_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                account_id,
                                symbol,
                                exchange,
                                currency,
                                side,
                                float(qty),
                                float(price),
                                float(commission),
                                float(realized),
                                trade_time,
                                exec_id,
                                perm_id,
                            ),
                        )
                        conn.commit()
                        mark_update()
                    except psycopg.IntegrityError:
                        span_end("db.insert_trade", span, "integrity_error")
                        logged = True
                        return
                    finally:
                        if not logged:
                            span_end(
                                "db.insert_trade",
                                span,
                                f"symbol={symbol} exchange={exchange} qty={qty} price={price}",
                            )
                    if exec_id and exec_id in pending_commission_reports:
                        pending = pending_commission_reports.pop(exec_id)
                        update_trade_from_report(exec_id, pending[0], pending[1])
                    maybe_update_open_time(symbol, currency, trade_time)
                    maybe_update_history_from_trade(
                        symbol,
                        exchange,
                        currency,
                        trade_time,
                        realized,
                    )

                def on_exec(trade_or_fill, fill=None):
                    span = span_start("on_exec")
                    ensure_conn()
                    if fill is None:
                        fill = trade_or_fill
                        contract = fill.contract
                    else:
                        contract = trade_or_fill.contract
                    execution = getattr(fill, "execution", None)
                    if execution is None:
                        span_end("on_exec", span, "missing execution")
                        return
                    exec_account = getattr(execution, "acctNumber", None) or getattr(
                        execution, "account", None
                    )
                    if exec_account and exec_account != account:
                        span_end("on_exec", span, f"skip account={exec_account}")
                        return
                    trade_exchange = _resolve_trade_exchange(
                        conn,
                        account_id,
                        contract.symbol,
                        contract.currency,
                        contract.exchange or "",
                    )
                    exec_id = execution.execId or None
                    perm_id = execution.permId if execution.permId else None
                    commission = 0.0
                    realized = 0.0
                    report = getattr(fill, "commissionReport", None)
                    if report:
                        commission = float(report.commission or 0.0)
                        realized = float(report.realizedPNL or 0.0)
                    insert_trade(
                        contract.symbol,
                        trade_exchange,
                        contract.currency,
                        _normalize_side(execution.side),
                        float(execution.shares),
                        float(execution.price),
                        commission,
                        realized,
                        _trade_time(getattr(fill, "time", None)),
                        exec_id,
                        perm_id,
                    )
                    if exec_id:
                        position_key = (
                            contract.symbol,
                            trade_exchange,
                            contract.currency,
                        )
                        self._cache.record_exec_realized(exec_id, position_key, realized)
                        update_position_realized_db(position_key)
                    span_end("on_exec", span, f"symbol={contract.symbol} exec_id={exec_id}")

                def on_commission(*args):
                    span = span_start("on_commission")
                    if len(args) == 1:
                        report = args[0]
                    elif len(args) >= 3:
                        report = args[2]
                    else:
                        span_end("on_commission", span, "no report")
                        return
                    exec_id = getattr(report, "execId", None)
                    if not exec_id:
                        span_end("on_commission", span, "missing exec_id")
                        return
                    commission = float(getattr(report, "commission", 0.0) or 0.0)
                    realized = float(getattr(report, "realizedPNL", 0.0) or 0.0)
                    update_trade_from_report(exec_id, commission, realized)
                    span_end("on_commission", span, f"exec_id={exec_id}")

                def on_pnl(*args) -> None:
                    span = span_start("on_pnl")
                    account_code = None
                    daily = None
                    unrealized = None
                    realized = None
                    if len(args) == 1:
                        pnl = args[0]
                        account_code = getattr(pnl, "account", None)
                        daily = getattr(pnl, "dailyPnL", None)
                        unrealized = getattr(pnl, "unrealizedPnL", None)
                        realized = getattr(pnl, "realizedPnL", None)
                    elif len(args) == 4:
                        account_code, daily, unrealized, realized = args
                    elif len(args) >= 5:
                        account_code = args[0]
                        daily = args[2]
                        unrealized = args[3]
                        realized = args[4]
                    if account_code and account_code != account:
                        span_end("on_pnl", span, f"skip account={account_code}")
                        return
                    realized_value = coerce_float(realized)
                    unrealized_value = coerce_float(unrealized)
                    if realized_value is None or unrealized_value is None:
                        span_end("on_pnl", span, "invalid values")
                        return
                    daily_value = coerce_float(daily)
                    if daily_value is None:
                        daily_value = 0.0
                    update_account_daily_pnl(daily_value)
                    mark_update()
                    span_end(
                        "on_pnl",
                        span,
                        f"daily={daily_value} unrealized={unrealized_value} realized={realized_value}",
                    )

                def on_error(
                    req_id: int, error_code: int, error_string: str, contract=None, *args
                ) -> None:
                    if error_code == 1100:
                        self._status.ibkr_connected = False
                        self._status.ibkr_last_disconnected_at = _utc_now()
                        return
                    if error_code in {1101, 1102}:
                        self._status.ibkr_connected = True
                        self._status.ibkr_last_connected_at = _utc_now()

                def on_account_summary(*args) -> None:
                    span = span_start("on_account_summary")
                    if len(args) == 1:
                        item = args[0]
                        account_code = getattr(item, "account", None)
                        tag = getattr(item, "tag", None)
                        value = getattr(item, "value", None)
                        currency = getattr(item, "currency", None)
                    elif len(args) >= 4:
                        account_code = args[1]
                        tag = args[2]
                        value = args[3]
                        currency = args[4] if len(args) >= 5 else None
                    else:
                        span_end("on_account_summary", span, "invalid args")
                        return
                    if account_code and account_code != account:
                        span_end("on_account_summary", span, f"skip account={account_code}")
                        return
                    if currency and currency not in {"", "BASE", self.settings.base_currency}:
                        span_end("on_account_summary", span, f"skip currency={currency}")
                        return
                    if not tag:
                        span_end("on_account_summary", span, "missing tag")
                        return
                    value_number = coerce_float(value)
                    if value_number is None:
                        span_end("on_account_summary", span, "invalid value")
                        return
                    column = update_account_summary(tag, value_number)
                    if column:
                        summary_snapshot = self._cache.snapshot_account_summary()
                        flush_account_summary(summary_snapshot, {column})
                    span_end("on_account_summary", span, f"tag={tag} value={value_number}")

                def subscribe_pnl(con_id: int | None) -> None:
                    if not con_id or con_id in pnl_req_by_con:
                        return
                    try:
                        pnl = ib.reqPnLSingle(account, "", con_id)
                    except Exception:
                        return
                    req_id = getattr(pnl, "reqId", None)
                    if req_id is None:
                        return
                    pnl_req_by_con[con_id] = req_id
                    con_by_req[req_id] = con_id

                def unsubscribe_pnl(con_id: int | None) -> None:
                    if not con_id:
                        return
                    req_id = pnl_req_by_con.pop(con_id, None)
                    if req_id is None:
                        return
                    con_by_req.pop(req_id, None)
                    try:
                        ib.cancelPnLSingle(req_id)
                    except Exception:
                        return

                def archive_position(row: dict) -> None:
                    span = span_start(
                        "db.archive_position",
                        f"symbol={row.get('symbol')} exchange={row.get('exchange')}",
                    )
                    ensure_conn()
                    open_time = row["open_time"]
                    close_time = _get_last_trade_time(
                        conn, account_id, row["symbol"], row["currency"]
                    ) or _utc_now()
                    realized = _sum_realized(
                        conn, account_id, row["symbol"], row["currency"], open_time, close_time
                    )
                    conn.execute(
                        """
                        INSERT INTO positions_history
                            (id, account_id, symbol, exchange, currency, qty, avg_cost, total_cost,
                             realized_pnl, open_time, close_time, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            row["id"],
                            row["account_id"],
                            row["symbol"],
                            row["exchange"],
                            row["currency"],
                            row["qty"],
                            row["avg_cost"],
                            row["total_cost"],
                            realized,
                            row["open_time"],
                            close_time,
                            _utc_now(),
                        ),
                    )
                    conn.execute("DELETE FROM positions WHERE id = %s", (row["id"],))
                    conn.commit()
                    self._cache.add_history(
                        position_id=int(row["id"]),
                        symbol=row["symbol"],
                        exchange=row["exchange"] or "",
                        currency=row["currency"],
                        open_time=row["open_time"],
                        close_time=close_time,
                        realized_pnl=realized,
                    )
                    self._cache.remove_position(
                        row["symbol"],
                        row["exchange"] or "",
                        row["currency"],
                    )
                    unsubscribe_pnl(row["con_id"])
                    mark_update()
                    span_end(
                        "db.archive_position",
                        span,
                        f"symbol={row.get('symbol')} exchange={row.get('exchange')}",
                    )

                def on_position(*args):
                    span = span_start("on_position")
                    symbol = ""
                    exchange = ""
                    qty = ""
                    try:
                        ensure_conn()
                        if len(args) == 1 and isinstance(args[0], Position):
                            pos = args[0]
                            account_code = pos.account
                            contract = pos.contract
                            position = pos.position
                            avg_cost = pos.avgCost
                        elif len(args) >= 4:
                            account_code, contract, position, avg_cost = args[:4]
                        else:
                            return
                        if account_code != account:
                            return
                        symbol = contract.symbol
                        exchange = contract.exchange or ""
                        currency = contract.currency
                        qty = float(position)
                        avg_cost_value = float(avg_cost or 0.0)
                        if qty == 0.0:
                            row = conn.execute(
                                """
                                SELECT *
                                FROM positions
                                WHERE account_id = %s AND symbol = %s AND exchange = %s AND currency = %s
                                """,
                                (account_id, symbol, exchange, currency),
                            ).fetchone()
                            if row:
                                archive_position(row)
                            return

                        row = conn.execute(
                            """
                            SELECT id, open_time, unrealized_pnl, daily_pnl
                            FROM positions
                            WHERE account_id = %s AND symbol = %s AND exchange = %s AND currency = %s
                            """,
                            (account_id, symbol, exchange, currency),
                        ).fetchone()
                        open_time = row["open_time"] if row and row["open_time"] else None
                        if not open_time:
                            last_close = _get_last_close_time(conn, account_id, symbol, currency)
                            open_time = _get_first_trade_time(
                                conn, account_id, symbol, currency, after_time=last_close
                            ) or _utc_now()
                        unrealized_value = float(row["unrealized_pnl"]) if row else 0.0
                        daily_value = float(row["daily_pnl"]) if row else 0.0
                        new_row = conn.execute(
                            """
                            INSERT INTO positions
                                (account_id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl,
                                 unrealized_pnl, daily_pnl, con_id, open_time, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT(account_id, symbol, exchange, currency) DO UPDATE
                            SET qty = excluded.qty,
                                avg_cost = excluded.avg_cost,
                                total_cost = excluded.total_cost,
                                con_id = excluded.con_id,
                                open_time = COALESCE(positions.open_time, excluded.open_time),
                                updated_at = excluded.updated_at
                            RETURNING id
                            """,
                            (
                                account_id,
                                symbol,
                                exchange,
                                currency,
                                qty,
                                avg_cost_value,
                                qty * avg_cost_value,
                                0.0,
                                unrealized_value,
                                daily_value,
                                contract.conId,
                                open_time,
                                _utc_now(),
                            ),
                        ).fetchone()
                        conn.commit()
                        position_id = int(new_row["id"]) if new_row else None
                        self._cache.update_position(
                            position_id=position_id,
                            symbol=symbol,
                            exchange=exchange,
                            currency=currency,
                            qty=qty,
                            avg_cost=avg_cost_value,
                            open_time=open_time,
                            con_id=contract.conId,
                        )
                        subscribe_pnl(contract.conId)
                        mark_update()
                    finally:
                        extra = f"symbol={symbol} qty={qty} exchange={exchange}".strip()
                        span_end("on_position", span, extra)

                def request_positions() -> None:
                    span = span_start("request_positions")
                    ensure_conn()
                    try:
                        positions = ib.reqPositions()
                    except Exception:
                        span_end("request_positions", span, "exception")
                        return
                    seen: set[tuple[str, str, str]] = set()
                    for pos in positions:
                        if pos.account != account:
                            continue
                        on_position(pos)
                        seen.add((pos.contract.symbol, pos.contract.exchange or "", pos.contract.currency))
                    rows = conn.execute(
                        "SELECT * FROM positions WHERE account_id = %s",
                        (account_id,),
                    ).fetchall()
                    for row in rows:
                        key = (row["symbol"], row["exchange"], row["currency"])
                        if key in seen:
                            continue
                        archive_position(row)
                    span_end("request_positions", span, f"count={len(positions)}")

                def request_executions() -> None:
                    span = span_start("request_executions")
                    try:
                        fills = ib.reqExecutions()
                        for fill in fills:
                            on_exec(fill)
                    except Exception:
                        span_end("request_executions", span, "exception")
                        return
                    span_end("request_executions", span, f"count={len(fills)}")

                def request_account_pnl() -> None:
                    span = span_start("request_account_pnl")
                    nonlocal account_pnl_req_id
                    try:
                        pnl = ib.reqPnL(account, "")
                    except Exception:
                        span_end("request_account_pnl", span, "exception")
                        return
                    account_pnl_req_id = getattr(pnl, "reqId", None)
                    span_end("request_account_pnl", span, f"req_id={account_pnl_req_id}")

                def request_account_summary() -> None:
                    span = span_start("request_account_summary")
                    nonlocal account_summary_req_id
                    try:
                        get_req_id = getattr(ib.client, "getReqId", None)
                        if callable(get_req_id):
                            account_summary_req_id = get_req_id()
                        else:
                            account_summary_req_id = int(time.time())
                        tags = ",".join(_ACCOUNT_SUMMARY_TAGS.keys())
                        ib.client.reqAccountSummary(account_summary_req_id, "All", tags)
                    except Exception:
                        span_end("request_account_summary", span, "exception")
                        return
                    span_end("request_account_summary", span, f"req_id={account_summary_req_id}")

                def process_order(job: OrderJob) -> None:
                    payload = job.payload
                    try:
                        logger.info(
                            "Placing order request_id=%s symbol=%s side=%s qty=%s type=%s price=%s",
                            job.request_id,
                            payload.symbol,
                            payload.side,
                            payload.qty,
                            payload.order_type,
                            payload.price,
                        )
                        contract = Stock(
                            payload.symbol.strip().upper(),
                            payload.exchange or "SMART",
                            payload.currency or self.settings.base_currency,
                        )
                        qualified = ib.qualifyContracts(contract)
                        if not qualified:
                            logger.warning(
                                "Order failed to qualify request_id=%s symbol=%s exchange=%s currency=%s",
                                job.request_id,
                                payload.symbol,
                                payload.exchange,
                                payload.currency,
                            )
                            set_order_result(
                                job.request_id,
                                OrderResult(success=False, error="Unable to qualify contract"),
                            )
                            return
                        action = "BUY" if payload.side.lower() == "buy" else "SELL"
                        qty = float(payload.qty)
                        if payload.order_type.upper() in {"MKT", "MARKET"}:
                            order = MarketOrder(action, qty)
                        else:
                            if payload.price is None:
                                set_order_result(
                                    job.request_id,
                                    OrderResult(success=False, error="Limit price required"),
                                )
                                return
                            order = LimitOrder(action, qty, float(payload.price))
                        if payload.tif:
                            order.tif = payload.tif
                        if payload.account:
                            order.account = payload.account
                        trade = ib.placeOrder(contract, order)
                        ib.sleep(1)
                        status = trade.orderStatus
                        logger.info(
                            "Order placed request_id=%s order_id=%s status=%s filled=%s remaining=%s avg_fill=%s",
                            job.request_id,
                            trade.order.orderId,
                            status.status,
                            status.filled,
                            status.remaining,
                            status.avgFillPrice,
                        )
                        set_order_result(
                            job.request_id,
                            OrderResult(
                                success=True,
                                result={
                                    "order_id": trade.order.orderId,
                                    "status": status.status,
                                    "filled": status.filled,
                                    "remaining": status.remaining,
                                    "avg_fill_price": status.avgFillPrice,
                                    "request_id": job.request_id,
                                },
                                request_id=job.request_id,
                            ),
                        )
                    except Exception as exc:
                        logger.exception("Order error request_id=%s", job.request_id)
                        set_order_result(
                            job.request_id,
                            OrderResult(success=False, error=str(exc), request_id=job.request_id),
                        )

                def on_pnl_single(*args) -> None:
                    con_id = None
                    unrealized = None
                    daily = None
                    if len(args) == 1:
                        pnl = args[0]
                        con_id = getattr(pnl, "conId", None)
                        unrealized = getattr(pnl, "unrealizedPnL", None)
                        daily = getattr(pnl, "dailyPnL", None)
                    elif len(args) >= 4:
                        req_id = args[0]
                        con_id = con_by_req.get(req_id)
                        if len(args) >= 5:
                            daily = args[2]
                            unrealized = args[3]
                            if daily is None and len(args) >= 5:
                                daily = args[4]
                        else:
                            daily = args[1]
                            unrealized = args[2]
                    if con_id is None or unrealized is None:
                        return
                    try:
                        unrealized_value = float(unrealized)
                    except (TypeError, ValueError):
                        return
                    if not math.isfinite(unrealized_value):
                        return
                    daily_value = None
                    if daily is not None:
                        try:
                            daily_value = float(daily)
                        except (TypeError, ValueError):
                            daily_value = None
                        if daily_value is not None and not math.isfinite(daily_value):
                            daily_value = None
                    last_entry = last_pnl_single.get(con_id)
                    if last_entry:
                        last_daily, last_unrealized = last_entry
                        if last_daily == daily_value and last_unrealized == unrealized_value:
                            return
                    last_pnl_single[con_id] = (daily_value, unrealized_value)
                    pending_pnl_single[con_id] = (unrealized_value, daily_value)
                    self._cache.update_position_pnl_by_con_id(
                        con_id, unrealized_value, daily_value
                    )

                def flush_pnl_single_updates() -> None:
                    if not pending_pnl_single:
                        return
                    count = len(pending_pnl_single)
                    span = span_start("flush_pnl_single", f"count={count}")
                    try:
                        ensure_conn()
                        now = _utc_now()
                        updates_with_daily: list[tuple[float, float, str, int, int]] = []
                        updates_without_daily: list[tuple[float, str, int, int]] = []
                        for con_id, values in pending_pnl_single.items():
                            unrealized_value, daily_value = values
                            if daily_value is None:
                                updates_without_daily.append(
                                    (unrealized_value, now, account_id, con_id)
                                )
                            else:
                                updates_with_daily.append(
                                    (unrealized_value, daily_value, now, account_id, con_id)
                                )
                        with conn.cursor() as cur:
                            if updates_without_daily:
                                cur.executemany(
                                    """
                                    UPDATE positions
                                    SET unrealized_pnl = %s, updated_at = %s
                                    WHERE account_id = %s AND con_id = %s
                                    """,
                                    updates_without_daily,
                                )
                            if updates_with_daily:
                                cur.executemany(
                                    """
                                    UPDATE positions
                                    SET unrealized_pnl = %s, daily_pnl = %s, updated_at = %s
                                    WHERE account_id = %s AND con_id = %s
                                    """,
                                    updates_with_daily,
                                )
                        conn.commit()
                        mark_update()
                        pending_pnl_single.clear()
                    finally:
                        span_end("flush_pnl_single", span, f"count={count}")

                def flush_account_daily_pnl(daily_payload: dict[str, float] | None) -> None:
                    if not daily_payload or account_id is None:
                        return
                    span = span_start("flush_account_daily_pnl")
                    try:
                        ensure_conn()
                        now = _utc_now()
                        conn.execute(
                            """
                            INSERT INTO account_daily_pnl
                                (account_id, trade_date, daily_pnl, cumulative_pnl, updated_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT(account_id, trade_date) DO UPDATE
                            SET daily_pnl = excluded.daily_pnl,
                                cumulative_pnl = excluded.cumulative_pnl,
                                updated_at = excluded.updated_at
                            """,
                            (
                                account_id,
                                daily_payload["trade_date"],
                                float(daily_payload["daily_pnl"]),
                                float(daily_payload["cumulative_pnl"]),
                                now,
                            ),
                        )
                        conn.commit()
                        self._cache.clear_dirty(daily_pnl=True)
                        mark_update()
                    finally:
                        span_end("flush_account_daily_pnl", span)

                def flush_account_summary(
                    account_summary: dict[str, float] | None, summary_fields: set[str]
                ) -> None:
                    if not account_summary or not summary_fields or account_id is None:
                        return
                    span = span_start("flush_account_summary")
                    try:
                        ensure_conn()
                        now = _utc_now()
                        columns = sorted(summary_fields)
                        placeholders = ", ".join(["%s"] * (len(columns) + 2))
                        insert_cols = ", ".join(["account_id", *columns, "updated_at"])
                        updates = ", ".join(
                            [f"{column} = excluded.{column}" for column in columns]
                            + ["updated_at = excluded.updated_at"]
                        )
                        values = [account_id]
                        values.extend([account_summary.get(column) for column in columns])
                        values.append(now)
                        conn.execute(
                            f"""
                            INSERT INTO account_summary ({insert_cols})
                            VALUES ({placeholders})
                            ON CONFLICT(account_id) DO UPDATE
                            SET {updates}
                            """,
                            values,
                        )
                        conn.commit()
                        self._cache.clear_dirty(account_summary_fields=summary_fields)
                        mark_update()
                    finally:
                        span_end("flush_account_summary", span)

                ib.execDetailsEvent += on_exec
                ib.commissionReportEvent += on_commission
                ib.positionEvent += on_position
                ib.pnlEvent += on_pnl
                ib.accountSummaryEvent += on_account_summary
                ib.pnlSingleEvent += on_pnl_single
                ib.errorEvent += on_error

                request_positions()
                logger.info("request_positions done")
                request_executions()
                logger.info("request_executions done")
                request_account_pnl()
                logger.info("request_account_pnl done")
                request_account_summary()
                logger.info("request_account_summary done")

                backoff = max(1, self.settings.ib_reconnect_min_delay)
                last_keepalive = time.time()
                last_queue_log = 0.0
                last_cache_flush = time.time()

                logger.info("enter order loop")
                while not self._stop_event.is_set() and ib.isConnected():
                    loop_span = span_start("order_loop_tick")
                    sleep_span = span_start("ib.sleep")
                    ib.sleep(1)
                    span_end("ib.sleep", sleep_span)
                    if time.time() - last_keepalive >= self.settings.ib_keepalive_seconds:
                        ib.reqCurrentTime()
                        last_keepalive = time.time()
                    if time.time() - last_cache_flush >= self.settings.ib_cache_flush_seconds:
                        flush_pnl_single_updates()
                        account_summary, summary_fields, daily_payload = (
                            self._cache.collect_flush_payload()
                        )
                        flush_account_daily_pnl(daily_payload)
                        flush_account_summary(account_summary, summary_fields)
                        last_cache_flush = time.time()
                    now = time.time()
                    if now - last_queue_log >= 5:
                        last_queue_log = now
                        logger.info("Order queue size=%s", self._order_queue.qsize())
                    while True:
                        try:
                            job = self._order_queue.get_nowait()
                        except Empty:
                            break
                        logger.info("Order dequeued request_id=%s", job.request_id)
                        process_order(job)
                        self._order_queue.task_done()
                    span_end("order_loop_tick", loop_span)

                if not self._stop_event.is_set():
                    self._status.connected = False
                    self._status.last_disconnected_at = _utc_now()
                    self._status.ibkr_connected = False
                    self._status.ibkr_last_disconnected_at = _utc_now()
                    self._status.error = "Disconnected from IB Gateway"

            except Exception as exc:  # pragma: no cover
                self._status.connected = False
                self._status.last_disconnected_at = _utc_now()
                self._status.ibkr_connected = False
                self._status.ibkr_last_disconnected_at = _utc_now()
                self._status.error = str(exc)
            finally:
                if conn:
                    conn.close()
                try:
                    ib.disconnect()
                except Exception:
                    pass
                with self._order_lock:
                    pending_ids = list(self._order_waiters.keys())
                for request_id in pending_ids:
                    set_order_result(
                        request_id,
                        OrderResult(
                            success=False,
                            error="IB Gateway disconnected",
                            request_id=request_id,
                        ),
                    )

            if self._stop_event.is_set():
                break

            time.sleep(backoff)
            backoff = min(backoff * 2, self.settings.ib_reconnect_max_delay)

        self._status.running = False


def seed_demo_data(settings: Settings) -> None:
    conn = get_connection(settings.database_url)
    account_id = upsert_account(conn, "DEMO", settings.base_currency)
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)

    trades = [
        ("buy", 10, 410.0, 1.0, now.isoformat(), "demo-1"),
        ("sell", 5, 420.0, 1.0, (now + dt.timedelta(days=1)).isoformat(), "demo-2"),
        ("buy", 4, 415.0, 1.0, (now + dt.timedelta(days=2)).isoformat(), "demo-3"),
    ]

    for side, qty, price, commission, trade_time, exec_id in trades:
        conn.execute(
            """
            INSERT INTO trades
                (account_id, symbol, exchange, currency, side, qty, price, commission, realized_pnl,
                 trade_time, ibkr_exec_id, perm_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                account_id,
                "MSFT",
                "NASDAQ",
                "USD",
                side,
                qty,
                price,
                commission,
                0.0,
                trade_time,
                exec_id,
                None,
            ),
        )
    conn.commit()
