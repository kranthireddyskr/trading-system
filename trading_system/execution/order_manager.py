from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from trading_system.execution.alpaca import AlpacaBroker
from trading_system.execution.base import BrokerBase
from trading_system.execution.paper import PaperBroker
from trading_system.storage.models import Fill, Order


class OrderManager:
    def __init__(self, broker: BrokerBase, timeout_seconds: int = 30) -> None:
        self.broker = broker
        self.timeout_seconds = timeout_seconds
        self.active_orders: dict[str, Order] = {}

    def __repr__(self) -> str:
        return f"OrderManager(timeout_seconds={self.timeout_seconds}, active_orders={len(self.active_orders)})"

    def submit(self, **kwargs) -> Order:
        order = self.broker.submit_order(**kwargs)
        self.active_orders[order.order_id] = order
        return order

    def maybe_cancel_expired(self) -> list[str]:
        cancelled = []
        now = datetime.utcnow()
        for order_id, order in list(self.active_orders.items()):
            if order.status == "filled":
                continue
            if now - order.submitted_at > timedelta(seconds=self.timeout_seconds):
                self.broker.cancel_order(order_id)
                order.status = "cancelled"
                cancelled.append(order_id)
                del self.active_orders[order_id]
        return cancelled

    def fill_order(self, order: Order, market_price: float) -> Optional[Fill]:
        if isinstance(self.broker, PaperBroker):
            fill = self.broker.simulate_fill(order, market_price)
            self.active_orders.pop(order.order_id, None)
            return fill
        return None

    def sync_open_orders(self, market_prices: dict[str, float] | None = None) -> list[Fill]:
        fills: list[Fill] = []
        market_prices = market_prices or {}
        if isinstance(self.broker, PaperBroker):
            return fills
        if not isinstance(self.broker, AlpacaBroker):
            return fills
        for order_id, order in list(self.active_orders.items()):
            try:
                payload = self.broker.get_order(order_id)
            except Exception:
                continue
            order.status = str(payload.get("status", order.status))
            fill = self.broker.order_to_fill(payload, expected_price=market_prices.get(order.symbol, order.limit_price or order.stop_price or 0.0))
            if fill is not None:
                fills.append(fill)
                self.active_orders.pop(order_id, None)
                continue
            if order.status in {"canceled", "expired", "rejected"}:
                self.active_orders.pop(order_id, None)
        return fills
