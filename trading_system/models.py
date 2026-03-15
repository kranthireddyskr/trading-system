from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class MarketBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str
    timeframe: str = "1Min"


@dataclass(frozen=True)
class QuoteTick:
    symbol: str
    timestamp: datetime
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    provider: str


@dataclass(frozen=True)
class TradeTick:
    symbol: str
    timestamp: datetime
    price: float
    size: float
    provider: str


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    symbol: str
    timestamp: datetime
    headline: str
    summary: str
    sentiment_score: float
    provider: str


@dataclass(frozen=True)
class Signal:
    symbol: str
    timestamp: datetime
    side: str
    score: float
    price: float
    metadata: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    quantity: int
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class Position:
    symbol: str
    entry_time: datetime
    entry_price: float
    quantity: int
    stop_loss: float
    take_profit: float
    side: str = "LONG"
    broker_order_id: str = ""


@dataclass
class FillEvent:
    order_id: str
    symbol: str
    side: str
    timestamp: datetime
    quantity: int
    requested_price: float
    fill_price: float
    commission: float
    slippage: float
    provider: str


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    reason: str
    entry_order_id: str
    exit_order_id: str


@dataclass
class AccountSnapshot:
    timestamp: datetime
    equity: float
    cash: float
    buying_power: float
    daily_start_equity: float
    open_positions: int
    gross_exposure: float


@dataclass
class EngineState:
    bars_by_symbol: Dict[str, List[MarketBar]] = field(default_factory=dict)
    news_by_symbol: Dict[str, List[NewsEvent]] = field(default_factory=dict)
    positions: Dict[str, Position] = field(default_factory=dict)
    processed_news_ids: set = field(default_factory=set)

