from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

import requests

from trading_system.config.settings import Settings
from trading_system.execution.base import BrokerBase
from trading_system.storage.models import Fill, Order


class AlpacaBroker(BrokerBase):
    def __init__(self, settings: Settings, paper: bool = True) -> None:
        self.settings = settings
        self.base_url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        self.headers = {
            "APCA-API-KEY-ID": settings.apca_api_key_id,
            "APCA-API-SECRET-KEY": settings.apca_api_secret_key,
            "Content-Type": "application/json",
        }

    def __repr__(self) -> str:
        return f"AlpacaBroker(base_url={self.base_url!r})"

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        for attempt in range(5):
            try:
                response = requests.request(method, self.base_url + path, headers=self.headers, json=payload, timeout=20)
                if response.status_code == 429:
                    time.sleep(min(2 ** attempt, 10))
                    continue
                if response.status_code == 400:
                    raise RuntimeError(f"Bad request: {response.text}")
                if response.status_code == 401:
                    raise RuntimeError("Unauthorized Alpaca credentials")
                if response.status_code == 403:
                    raise RuntimeError("Forbidden Alpaca request")
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                if attempt == 4:
                    raise RuntimeError(f"Alpaca request failed: {exc}") from exc
                time.sleep(min(2 ** attempt, 10))
        raise RuntimeError("Alpaca request failed after retries")

    def submit_order(self, **kwargs: Any) -> Order:
        client_order_id = f"order-{uuid.uuid4().hex[:14]}"
        payload = {
            "symbol": kwargs["symbol"],
            "qty": kwargs["qty"],
            "side": kwargs["side"],
            "type": kwargs.get("order_type", "market"),
            "time_in_force": kwargs.get("time_in_force", "day"),
            "client_order_id": client_order_id,
        }
        if kwargs.get("limit_price") is not None:
            payload["limit_price"] = kwargs["limit_price"]
        if kwargs.get("stop_price") is not None:
            payload["stop_price"] = kwargs["stop_price"]
        if kwargs.get("take_profit_price") is not None or kwargs.get("stop_loss_price") is not None:
            payload["order_class"] = "bracket"
            payload["take_profit"] = {"limit_price": kwargs.get("take_profit_price")}
            payload["stop_loss"] = {"stop_price": kwargs.get("stop_loss_price")}
        result = self._request("POST", "/v2/orders", payload)
        return Order(
            order_id=str(result.get("id", client_order_id)),
            symbol=str(result["symbol"]),
            side=str(result["side"]),
            qty=float(result.get("qty", kwargs["qty"])),
            order_type=str(result.get("type", payload["type"])),
            submitted_at=datetime.fromisoformat(result["created_at"].replace("Z", "+00:00")) if result.get("created_at") else datetime.utcnow(),
            limit_price=result.get("limit_price"),
            stop_price=result.get("stop_price"),
            take_profit_price=kwargs.get("take_profit_price"),
            status=str(result.get("status", "submitted")),
            strategy=str(kwargs.get("strategy", "")),
        )

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v2/orders/{order_id}")

    def get_positions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v2/positions")

    def get_account(self) -> dict[str, Any]:
        return self._request("GET", "/v2/account")

    def get_orders(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v2/orders")

    def close_position(self, symbol: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v2/positions/{symbol}")

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v2/orders/{order_id}")

    def order_to_fill(self, order_payload: dict[str, Any], expected_price: float | None = None) -> Fill | None:
        status = str(order_payload.get("status", ""))
        if status not in {"filled", "partially_filled"}:
            return None
        filled_qty = float(order_payload.get("filled_qty") or order_payload.get("qty") or 0.0)
        if filled_qty <= 0:
            return None
        fill_price = float(order_payload.get("filled_avg_price") or expected_price or 0.0)
        expected = float(expected_price or fill_price)
        created_at = order_payload.get("filled_at") or order_payload.get("updated_at") or order_payload.get("created_at")
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else datetime.utcnow()
        return Fill(
            order_id=str(order_payload.get("id")),
            symbol=str(order_payload.get("symbol")),
            side=str(order_payload.get("side")),
            qty=filled_qty,
            expected_price=expected,
            fill_price=fill_price,
            slippage=round(abs(fill_price - expected), 2),
            commission=0.0,
            timestamp=timestamp,
        )
