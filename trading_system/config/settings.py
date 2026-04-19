from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

try:
    import boto3
except ImportError:  # pragma: no cover - local environments may not have AWS deps yet
    boto3 = None


def _load_secret_bundle() -> Dict[str, str]:
    region = os.getenv("AWS_REGION", "us-east-1")
    secret_id = os.getenv("SECRETS_MANAGER_SECRET_ID", "trading-bot/alpaca")
    if boto3 is None:
        return {}
    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_id)
        secret_string = response.get("SecretString", "{}")
        payload = json.loads(secret_string)
        return {str(key): str(value) for key, value in payload.items()}
    except Exception:
        return {}


_SECRET_CACHE = _load_secret_bundle()


def _get_env(name: str, default: str = "") -> str:
    if name in _SECRET_CACHE and _SECRET_CACHE[name]:
        return _SECRET_CACHE[name]
    return os.getenv(name, default)


@dataclass
class Settings:
    apca_api_key_id: str = _get_env("APCA_API_KEY_ID")
    apca_api_secret_key: str = _get_env("APCA_API_SECRET_KEY")
    apca_base_url: str = _get_env("APCA_BASE_URL", "https://paper-api.alpaca.markets")
    storage_dsn: str = _get_env("STORAGE_DSN")
    aws_region: str = _get_env("AWS_REGION", "us-east-1")
    secrets_manager_secret_id: str = _get_env("SECRETS_MANAGER_SECRET_ID", "trading-bot/alpaca")
    alert_email_to: str = _get_env("ALERT_EMAIL_TO")
    alert_email_from: str = _get_env("ALERT_EMAIL_FROM")
    alert_smtp_host: str = _get_env("ALERT_SMTP_HOST")
    alert_smtp_port: int = int(_get_env("ALERT_SMTP_PORT", "587") or "587")
    alert_smtp_username: str = _get_env("ALERT_SMTP_USERNAME")
    alert_smtp_password: str = _get_env("ALERT_SMTP_PASSWORD")
    dashboard_port: int = int(_get_env("DASHBOARD_PORT", "8080") or "8080")
    timezone: str = _get_env("TRADING_TIMEZONE", "America/New_York")
    poll_seconds: int = int(_get_env("POLL_SECONDS", "60") or "60")
    flush_interval_seconds: int = int(_get_env("FLUSH_INTERVAL_SECONDS", "5") or "5")
    log_level: str = _get_env("LOG_LEVEL", "INFO")
    # Universe / screening
    universe_size: int = int(_get_env("UNIVERSE_SIZE", "50") or "50")
    min_price: float = float(_get_env("MIN_PRICE", "10.0") or "10.0")
    min_avg_volume: int = int(_get_env("MIN_AVG_VOLUME", "1000000") or "1000000")
    # Sentiment gating
    sentiment_gate_threshold: float = float(_get_env("SENTIMENT_GATE_THRESHOLD", "0.1") or "0.1")
    # End-of-day behaviour
    close_positions_eod: bool = _get_env("CLOSE_POSITIONS_EOD", "true").lower() in {"1", "true", "yes"}
    # Bracket order risk parameters
    bracket_orders: bool = _get_env("BRACKET_ORDERS", "true").lower() in {"1", "true", "yes"}
    stop_loss_pct: float = float(_get_env("STOP_LOSS_PCT", "0.02") or "0.02")
    take_profit_pct: float = float(_get_env("TAKE_PROFIT_PCT", "0.04") or "0.04")

    def __repr__(self) -> str:
        return (
            f"Settings(apca_base_url={self.apca_base_url!r}, storage_dsn={'set' if self.storage_dsn else 'unset'}, "
            f"dashboard_port={self.dashboard_port}, poll_seconds={self.poll_seconds})"
        )


def ensure_watchlist(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    symbols = ["AAPL", "MSFT", "NVDA", "AMD", "TSLA"]
    with path.open("w", encoding="utf-8-sig") as handle:
        handle.write("\n".join(symbols) + "\n")
