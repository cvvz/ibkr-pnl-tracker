from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA_STATEMENTS: Iterable[str] = (
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ibkr_account TEXT NOT NULL UNIQUE,
        base_currency TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        position_id INTEGER,
        symbol TEXT NOT NULL,
        exchange TEXT,
        currency TEXT NOT NULL,
        side TEXT NOT NULL,
        qty REAL NOT NULL,
        price REAL NOT NULL,
        commission REAL NOT NULL DEFAULT 0,
        realized_pnl REAL NOT NULL DEFAULT 0,
        trade_time TEXT NOT NULL,
        ibkr_exec_id TEXT UNIQUE,
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        exchange TEXT,
        currency TEXT NOT NULL,
        qty REAL NOT NULL,
        avg_cost REAL NOT NULL,
        total_cost REAL NOT NULL,
        realized_pnl REAL NOT NULL DEFAULT 0,
        open_time TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(account_id, symbol, exchange, currency),
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions_history (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        exchange TEXT,
        currency TEXT NOT NULL,
        qty REAL NOT NULL,
        avg_cost REAL NOT NULL,
        total_cost REAL NOT NULL,
        realized_pnl REAL NOT NULL DEFAULT 0,
        open_time TEXT NOT NULL,
        close_time TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        exchange TEXT,
        currency TEXT NOT NULL,
        last REAL,
        bid REAL,
        ask REAL,
        update_time TEXT NOT NULL,
        UNIQUE(symbol, exchange, currency)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fx_rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_ccy TEXT NOT NULL,
        to_ccy TEXT NOT NULL,
        rate REAL NOT NULL,
        update_time TEXT NOT NULL,
        UNIQUE(from_ccy, to_ccy)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pnl_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        realized_pnl REAL NOT NULL,
        unrealized_pnl REAL NOT NULL,
        total_pnl REAL NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    )
    """,
)


def get_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        _ensure_column(conn, "trades", "position_id", "position_id INTEGER")
        _ensure_column(conn, "positions", "open_time", "open_time TEXT")
        conn.commit()


def upsert_account(conn: sqlite3.Connection, account: str, base_currency: str) -> int:
    conn.execute(
        """
        INSERT INTO accounts (ibkr_account, base_currency)
        VALUES (?, ?)
        ON CONFLICT(ibkr_account) DO UPDATE SET base_currency = excluded.base_currency
        """,
        (account, base_currency),
    )
    row = conn.execute(
        "SELECT id FROM accounts WHERE ibkr_account = ?",
        (account,),
    ).fetchone()
    return int(row["id"])


def execute_many(conn: sqlite3.Connection, sql: str, rows: Iterable[tuple[Any, ...]]) -> None:
    conn.executemany(sql, rows)
