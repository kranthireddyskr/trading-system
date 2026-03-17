from __future__ import annotations

from datetime import datetime
from typing import Any

from trading_system.storage.models import MarketBar


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def normalize_bar(payload: dict[str, Any], symbol: str, source: str) -> MarketBar:
    timestamp = _parse_timestamp(str(payload.get("t") or payload.get("timestamp")))
    close = float(payload.get("c") or payload.get("close") or 0.0)
    return MarketBar(
        symbol=symbol,
        timestamp=timestamp,
        open=float(payload.get("o") or payload.get("open") or close),
        high=float(payload.get("h") or payload.get("high") or close),
        low=float(payload.get("l") or payload.get("low") or close),
        close=close,
        volume=int(payload.get("v") or payload.get("volume") or 0),
        vwap=float(payload.get("vw") or payload.get("vwap") or close),
        source=source,
    )

