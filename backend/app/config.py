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
    ws_update_interval_seconds: float
    gateway_deployment: str
    gateway_namespace: str
    gateway_vnc_url: str
    gateway_restart_enabled: bool
    gateway_restart_file: str


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
    ib_cache_flush_seconds = float(os.getenv("IBKR_CACHE_FLUSH_SECONDS", "18"))
    ws_update_interval_seconds = float(os.getenv("IBKR_WS_UPDATE_INTERVAL_SECONDS", "0.3"))
    gateway_deployment = os.getenv("IBKR_GATEWAY_DEPLOYMENT", "ib-gateway")
    gateway_namespace = os.getenv("IBKR_GATEWAY_NAMESPACE", "default")
    gateway_vnc_url = os.getenv("IBKR_GATEWAY_VNC_URL", "")
    gateway_restart_enabled = os.getenv("IBKR_GATEWAY_RESTART_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    gateway_restart_file = os.getenv("IBKR_GATEWAY_RESTART_FILE", "")

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
        ws_update_interval_seconds=ws_update_interval_seconds,
        gateway_deployment=gateway_deployment,
        gateway_namespace=gateway_namespace,
        gateway_vnc_url=gateway_vnc_url,
        gateway_restart_enabled=gateway_restart_enabled,
        gateway_restart_file=gateway_restart_file,
    )
