from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from trading_system.storage.models import MarketBar, NewsEvent, Signal


class BaseStrategy(ABC):
    name: str = "base"
    params: dict[str, float] = {}
    warmup_periods: int = 1

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, params={self.params!r})"

    @abstractmethod
    def on_bar(self, bar: MarketBar) -> Optional[Signal]:
        raise NotImplementedError

    @abstractmethod
    def on_news(self, event: NewsEvent) -> Optional[Signal]:
        raise NotImplementedError

