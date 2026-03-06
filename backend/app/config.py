from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    base_currency: str
    ib_host: str
    ib_port: int
    ib_client_id: int
    ib_order_client_id: int
    ib_order_queue_max: int
    ib_readonly: bool
    demo_mode: bool
    ib_auto_sync: bool
    ib_reconnect_min_delay: int
    ib_reconnect_max_delay: int
    ib_keepalive_seconds: int
    ib_cache_flush_seconds: float
    ib_total_pnl_flush_seconds: float
    ws_update_interval_seconds: float


def load_settings() -> Settings:
    database_url = os.getenv("IBKR_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("IBKR_DATABASE_URL (or DATABASE_URL) is required for Postgres")
    base_currency = os.getenv("IBKR_BASE_CURRENCY", "USD")
    ib_host = os.getenv("IBKR_HOST", "127.0.0.1")
    ib_port = int(os.getenv("IBKR_PORT", "7497"))
    ib_client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
    ib_order_client_id = int(os.getenv("IBKR_ORDER_CLIENT_ID", str(ib_client_id + 1)))
    ib_order_queue_max = int(os.getenv("IBKR_ORDER_QUEUE_MAX", "50"))
    ib_readonly = os.getenv("IBKR_READONLY", "false").lower() in {"1", "true", "yes"}
    demo_mode = os.getenv("IBKR_DEMO_MODE", "false").lower() in {"1", "true", "yes"}
    ib_auto_sync = os.getenv("IBKR_AUTO_SYNC", "true").lower() in {"1", "true", "yes"}
    ib_reconnect_min_delay = int(os.getenv("IBKR_RECONNECT_MIN_DELAY", "3"))
    ib_reconnect_max_delay = int(os.getenv("IBKR_RECONNECT_MAX_DELAY", "60"))
    ib_keepalive_seconds = int(os.getenv("IBKR_KEEPALIVE_SECONDS", "15"))
    ib_cache_flush_seconds = float(os.getenv("IBKR_CACHE_FLUSH_SECONDS", "30"))
    ib_total_pnl_flush_seconds = float(os.getenv("IBKR_TOTAL_PNL_FLUSH_SECONDS", "300"))
    ws_update_interval_seconds = float(os.getenv("IBKR_WS_UPDATE_INTERVAL_SECONDS", "0.3"))

    return Settings(
        database_url=database_url,
        base_currency=base_currency,
        ib_host=ib_host,
        ib_port=ib_port,
        ib_client_id=ib_client_id,
        ib_order_client_id=ib_order_client_id,
        ib_order_queue_max=ib_order_queue_max,
        ib_readonly=ib_readonly,
        demo_mode=demo_mode,
        ib_auto_sync=ib_auto_sync,
        ib_reconnect_min_delay=ib_reconnect_min_delay,
        ib_reconnect_max_delay=ib_reconnect_max_delay,
        ib_keepalive_seconds=ib_keepalive_seconds,
        ib_cache_flush_seconds=ib_cache_flush_seconds,
        ib_total_pnl_flush_seconds=ib_total_pnl_flush_seconds,
        ws_update_interval_seconds=ws_update_interval_seconds,
    )
