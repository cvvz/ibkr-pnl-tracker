from __future__ import annotations

from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

SCHEMA_STATEMENTS: Iterable[str] = (
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        ibkr_account TEXT NOT NULL UNIQUE,
        base_currency TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id SERIAL PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        position_id INTEGER,
        symbol TEXT NOT NULL,
        exchange TEXT,
        currency TEXT NOT NULL,
        side TEXT NOT NULL,
        qty DOUBLE PRECISION NOT NULL,
        price DOUBLE PRECISION NOT NULL,
        commission DOUBLE PRECISION NOT NULL DEFAULT 0,
        realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        trade_time TEXT NOT NULL,
        ibkr_exec_id TEXT UNIQUE,
        perm_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id SERIAL PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        symbol TEXT NOT NULL,
        exchange TEXT,
        currency TEXT NOT NULL,
        qty DOUBLE PRECISION NOT NULL,
        avg_cost DOUBLE PRECISION NOT NULL,
        total_cost DOUBLE PRECISION NOT NULL,
        realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        con_id INTEGER,
        open_time TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(account_id, symbol, exchange, currency)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions_history (
        id BIGINT PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        symbol TEXT NOT NULL,
        exchange TEXT,
        currency TEXT NOT NULL,
        qty DOUBLE PRECISION NOT NULL,
        avg_cost DOUBLE PRECISION NOT NULL,
        total_cost DOUBLE PRECISION NOT NULL,
        realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        open_time TEXT NOT NULL,
        close_time TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_pnl (
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
        realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        daily_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        total_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_summary (
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
        net_liquidation DOUBLE PRECISION,
        total_cash_value DOUBLE PRECISION,
        available_funds DOUBLE PRECISION,
        excess_liquidity DOUBLE PRECISION,
        init_margin_req DOUBLE PRECISION,
        maint_margin_req DOUBLE PRECISION,
        gross_position_value DOUBLE PRECISION,
        short_market_value DOUBLE PRECISION,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_daily_pnl (
        id SERIAL PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        trade_date TEXT NOT NULL,
        daily_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        cumulative_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        UNIQUE(account_id, trade_date)
    )
    """,
)


def get_connection(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


def init_db(database_url: str) -> None:
    with get_connection(database_url) as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS position_id INTEGER")
        conn.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS perm_id TEXT")
        conn.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS open_time TEXT")
        conn.execute(
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0"
        )
        conn.execute(
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS daily_pnl DOUBLE PRECISION NOT NULL DEFAULT 0"
        )
        conn.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS con_id INTEGER")
        conn.commit()


def upsert_account(conn: psycopg.Connection, account: str, base_currency: str) -> int:
    conn.execute(
        """
        INSERT INTO accounts (ibkr_account, base_currency)
        VALUES (%s, %s)
        ON CONFLICT(ibkr_account) DO UPDATE SET base_currency = excluded.base_currency
        """,
        (account, base_currency),
    )
    row = conn.execute(
        "SELECT id FROM accounts WHERE ibkr_account = %s",
        (account,),
    ).fetchone()
    return int(row["id"])


def execute_many(conn: psycopg.Connection, sql: str, rows: Iterable[tuple[Any, ...]]) -> None:
    conn.executemany(sql, rows)
