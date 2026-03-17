from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from trading_system.execution.base import BrokerBase
from trading_system.storage.models import Fill, Order


class PaperBroker(BrokerBase):
    def __init__(self, slippage_pct: float = 0.0005, commission: float = 0.0) -> None:
        self.slippage_pct = slippage_pct
        self.commission = commission
        self.orders: dict[str, Order] = {}

    def __repr__(self) -> str:
        return f"PaperBroker(slippage_pct={self.slippage_pct}, commission={self.commission})"

    def submit_order(self, **kwargs: Any) -> Order:
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        order = Order(
            order_id=order_id,
            symbol=str(kwargs["symbol"]),
            side=str(kwargs["side"]),
            qty=float(kwargs["qty"]),
            order_type=str(kwargs.get("order_type", "market")),
            submitted_at=datetime.utcnow(),
            limit_price=kwargs.get("limit_price"),
            stop_price=kwargs.get("stop_price"),
            take_profit_price=kwargs.get("take_profit_price"),
            strategy=str(kwargs.get("strategy", "")),
        )
        self.orders[order_id] = order
        return order

    def simulate_fill(self, order: Order, market_price: float) -> Fill:
        direction = 1 if order.side.lower() in {"buy", "long"} else -1
        fill_price = round(float(market_price) * (1 + (direction * self.slippage_pct)), 2)
        order.status = "filled"
        return Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            expected_price=market_price,
            fill_price=fill_price,
            slippage=round(abs(fill_price - market_price), 2),
            commission=self.commission,
            timestamp=datetime.utcnow(),
        )

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        if order_id in self.orders:
            self.orders[order_id].status = "cancelled"
        return {"order_id": order_id, "status": "cancelled"}

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def get_account(self) -> dict[str, Any]:
        return {"equity": "100000", "cash": "100000", "buying_power": "100000"}

    def get_orders(self) -> list[dict[str, Any]]:
        return [order.__dict__ for order in self.orders.values()]

    def close_position(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "status": "closed"}

