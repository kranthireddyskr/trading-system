from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from trading_system.storage.models import Fill, Order


class BrokerBase(ABC):
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"

    @abstractmethod
    def submit_order(self, **kwargs: Any) -> Order:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_account(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_orders(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def close_position(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError

