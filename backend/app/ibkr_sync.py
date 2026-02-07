from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass
from typing import Optional

from ib_insync import Forex, IB

from .config import Settings
from .db import get_connection, upsert_account
from .portfolio import apply_trade


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _bj_now() -> str:
    return dt.datetime.now(tz=dt.timezone(dt.timedelta(hours=8))).isoformat()


@dataclass
class SyncStatus:
    running: bool
    connected: bool = False
    error: Optional[str] = None
    started_at: Optional[str] = None
    last_update: Optional[str] = None
    last_connected_at: Optional[str] = None
    last_disconnected_at: Optional[str] = None


class IBKRSyncManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._status = SyncStatus(running=False)

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

    def _run(self) -> None:
        self._status = SyncStatus(running=True, started_at=_utc_now())
        backoff = max(1, self.settings.ib_reconnect_min_delay)

        while not self._stop_event.is_set():
            ib = IB()
            conn = None
            try:
                ib.connect(
                    self.settings.ib_host,
                    self.settings.ib_port,
                    clientId=self.settings.ib_client_id,
                    readonly=self.settings.ib_readonly,
                )
                self._status.connected = True
                self._status.last_connected_at = _utc_now()
                self._status.error = None

                conn = get_connection(self.settings.db_path)
                account = ib.managedAccounts()[0] if ib.managedAccounts() else "LOCAL"
                account_id = upsert_account(conn, account, self.settings.base_currency)

                contracts = {}
                fx_contracts = {}

                def on_exec(trade, fill):
                    contract = trade.contract
                    apply_trade(
                        conn,
                        account_id,
                        contract.symbol,
                        contract.exchange or "",
                        contract.currency,
                        fill.execution.side,
                        fill.execution.shares,
                        fill.execution.price,
                        fill.commissionReport.commission or 0.0,
                        fill.time.isoformat(),
                        fill.execution.execId,
                    )

                def on_position(account_code, contract, position, avg_cost):
                    if account_code != account:
                        return
                    conn.execute(
                        """
                        INSERT INTO positions (account_id, symbol, exchange, currency, qty, avg_cost, total_cost, realized_pnl, open_time, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(account_id, symbol, exchange, currency) DO UPDATE
                        SET qty = excluded.qty,
                            avg_cost = excluded.avg_cost,
                            total_cost = excluded.total_cost,
                            open_time = COALESCE(positions.open_time, excluded.open_time),
                            updated_at = excluded.updated_at
                        """,
                        (
                            account_id,
                            contract.symbol,
                            contract.exchange or "",
                            contract.currency,
                            float(position),
                            float(avg_cost),
                            float(position) * float(avg_cost),
                            0.0,
                            _bj_now(),
                            _utc_now(),
                        ),
                    )
                    conn.commit()
                    if contract.conId not in contracts:
                        contracts[contract.conId] = contract
                        ib.reqMktData(contract, "", False, False)

                    if contract.currency != self.settings.base_currency:
                        pair = f"{contract.currency}{self.settings.base_currency}"
                        if pair not in fx_contracts:
                            fx_contract = Forex(pair)
                            fx_contracts[pair] = fx_contract
                            ib.reqMktData(fx_contract, "", False, False)

                def on_tickers(tickers):
                    for ticker in tickers:
                        contract = ticker.contract
                        if isinstance(contract, Forex):
                            base = contract.pair[:3]
                            quote = contract.pair[3:]
                            conn.execute(
                                """
                                INSERT INTO fx_rates (from_ccy, to_ccy, rate, update_time)
                                VALUES (?, ?, ?, ?)
                                ON CONFLICT(from_ccy, to_ccy) DO UPDATE
                                SET rate = excluded.rate,
                                    update_time = excluded.update_time
                                """,
                                (base, quote, ticker.marketPrice(), _utc_now()),
                            )
                            conn.commit()
                        else:
                            conn.execute(
                                """
                                INSERT INTO prices (symbol, exchange, currency, last, bid, ask, update_time)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(symbol, exchange, currency) DO UPDATE
                                SET last = excluded.last,
                                    bid = excluded.bid,
                                    ask = excluded.ask,
                                    update_time = excluded.update_time
                                """,
                                (
                                    contract.symbol,
                                    contract.exchange or "",
                                    contract.currency,
                                    ticker.last,
                                    ticker.bid,
                                    ticker.ask,
                                    _utc_now(),
                                ),
                            )
                            conn.commit()
                    self._status.last_update = _utc_now()

                ib.execDetailsEvent += on_exec
                ib.positionEvent += on_position
                ib.pendingTickersEvent += on_tickers

                ib.reqPositions()
                ib.reqExecutions()

                backoff = max(1, self.settings.ib_reconnect_min_delay)
                last_keepalive = time.time()

                while not self._stop_event.is_set() and ib.isConnected():
                    ib.sleep(1)
                    if time.time() - last_keepalive >= self.settings.ib_keepalive_seconds:
                        ib.reqCurrentTime()
                        last_keepalive = time.time()

                if not self._stop_event.is_set():
                    self._status.connected = False
                    self._status.last_disconnected_at = _utc_now()
                    self._status.error = "Disconnected from IB Gateway"

            except Exception as exc:  # pragma: no cover
                self._status.connected = False
                self._status.last_disconnected_at = _utc_now()
                self._status.error = str(exc)
            finally:
                if conn:
                    conn.close()
                try:
                    ib.disconnect()
                except Exception:
                    pass

            if self._stop_event.is_set():
                break

            time.sleep(backoff)
            backoff = min(backoff * 2, self.settings.ib_reconnect_max_delay)

        self._status.running = False


def seed_demo_data(settings: Settings) -> None:
    conn = get_connection(settings.db_path)
    account_id = upsert_account(conn, "DEMO", settings.base_currency)
    now = dt.datetime.utcnow()

    trades = [
        ("buy", 10, 410.0, 1.0, now.isoformat(), "demo-1"),
        ("sell", 5, 420.0, 1.0, (now + dt.timedelta(days=1)).isoformat(), "demo-2"),
        ("buy", 4, 415.0, 1.0, (now + dt.timedelta(days=2)).isoformat(), "demo-3"),
    ]

    for side, qty, price, commission, trade_time, exec_id in trades:
        apply_trade(
            conn,
            account_id,
            "MSFT",
            "NASDAQ",
            "USD",
            side,
            qty,
            price,
            commission,
            trade_time,
            exec_id,
        )

    conn.execute(
        """
        INSERT INTO prices (symbol, exchange, currency, last, bid, ask, update_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, exchange, currency) DO UPDATE
        SET last = excluded.last, update_time = excluded.update_time
        """,
        ("MSFT", "NASDAQ", "USD", 425.0, 424.5, 425.5, _utc_now()),
    )
    conn.commit()
