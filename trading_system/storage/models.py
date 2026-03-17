from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class MarketRegime(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNKNOWN = "UNKNOWN"


@dataclass
class MarketBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float
    source: str

    def __post_init__(self) -> None:
        self.open = round(float(self.open), 2)
        self.high = round(float(self.high), 2)
        self.low = round(float(self.low), 2)
        self.close = round(float(self.close), 2)
        self.volume = int(self.volume)
        self.vwap = round(float(self.vwap), 2)

    def __repr__(self) -> str:
        return f"MarketBar(symbol={self.symbol!r}, timestamp={self.timestamp.isoformat()}, close={self.close:.2f}, volume={self.volume})"


@dataclass
class NewsEvent:
    symbol: str
    headline: str
    summary: str
    timestamp: datetime
    sentiment: float
    source: str

    def __post_init__(self) -> None:
        self.sentiment = round(float(self.sentiment), 2)

    def __repr__(self) -> str:
        return f"NewsEvent(symbol={self.symbol!r}, timestamp={self.timestamp.isoformat()}, sentiment={self.sentiment:.2f})"


@dataclass
class Signal:
    symbol: str
    direction: str
    strength: float
    strategy: str
    reason: str
    timestamp: datetime

    def __post_init__(self) -> None:
        self.strength = round(float(self.strength), 2)

    def __repr__(self) -> str:
        return f"Signal(symbol={self.symbol!r}, direction={self.direction!r}, strategy={self.strategy!r}, strength={self.strength:.2f})"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str
    qty: float
    order_type: str
    submitted_at: datetime
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    status: str = "submitted"
    strategy: str = ""

    def __post_init__(self) -> None:
        self.qty = round(float(self.qty), 2)
        if self.limit_price is not None:
            self.limit_price = round(float(self.limit_price), 2)
        if self.stop_price is not None:
            self.stop_price = round(float(self.stop_price), 2)
        if self.take_profit_price is not None:
            self.take_profit_price = round(float(self.take_profit_price), 2)

    def __repr__(self) -> str:
        return f"Order(order_id={self.order_id!r}, symbol={self.symbol!r}, side={self.side!r}, qty={self.qty:.2f}, status={self.status!r})"


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: str
    qty: float
    expected_price: float
    fill_price: float
    slippage: float
    commission: float
    timestamp: datetime

    def __post_init__(self) -> None:
        self.qty = round(float(self.qty), 2)
        self.expected_price = round(float(self.expected_price), 2)
        self.fill_price = round(float(self.fill_price), 2)
        self.slippage = round(float(self.slippage), 2)
        self.commission = round(float(self.commission), 2)

    def __repr__(self) -> str:
        return f"Fill(order_id={self.order_id!r}, symbol={self.symbol!r}, side={self.side!r}, qty={self.qty:.2f}, fill_price={self.fill_price:.2f})"


@dataclass
class Trade:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    strategy: str

    def __post_init__(self) -> None:
        self.entry_price = round(float(self.entry_price), 2)
        self.exit_price = round(float(self.exit_price), 2)
        self.qty = round(float(self.qty), 2)
        self.pnl = round(float(self.pnl), 2)

    def __repr__(self) -> str:
        return f"Trade(symbol={self.symbol!r}, side={self.side!r}, qty={self.qty:.2f}, pnl={self.pnl:.2f}, strategy={self.strategy!r})"


@dataclass
class SystemEvent:
    level: str
    message: str
    timestamp: datetime
    payload: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"SystemEvent(level={self.level!r}, timestamp={self.timestamp.isoformat()}, message={self.message!r})"


@dataclass
class Position:
    symbol: str
    side: str
    qty: float
    entry_price: float
    opened_at: datetime
    strategy: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    broker_order_id: str = ""

    def __post_init__(self) -> None:
        self.qty = round(float(self.qty), 2)
        self.entry_price = round(float(self.entry_price), 2)
        if self.stop_loss is not None:
            self.stop_loss = round(float(self.stop_loss), 2)
        if self.take_profit is not None:
            self.take_profit = round(float(self.take_profit), 2)

    def __repr__(self) -> str:
        return f"Position(symbol={self.symbol!r}, side={self.side!r}, qty={self.qty:.2f}, entry_price={self.entry_price:.2f})"
