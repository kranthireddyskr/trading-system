from __future__ import annotations

from collections import defaultdict
from typing import Optional

import pandas as pd

from trading_system.storage.models import MarketBar, NewsEvent, Signal
from trading_system.strategy.base import BaseStrategy
from trading_system.strategy.indicators import ensure_ta


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def __init__(self, lookback: int = 30, min_volume: int = 100000) -> None:
        self.lookback = lookback
        self.min_volume = min_volume
        self.params = {"lookback": float(lookback), "min_volume": float(min_volume)}
        self.warmup_periods = lookback
        self._bars: dict[str, list[MarketBar]] = defaultdict(list)

    def __repr__(self) -> str:
        return f"MomentumStrategy(lookback={self.lookback}, min_volume={self.min_volume})"

    def on_bar(self, bar: MarketBar) -> Optional[Signal]:
        history = self._bars[bar.symbol]
        history.append(bar)
        history[:] = history[-max(self.lookback, 60) :]
        if len(history) < self.warmup_periods:
            return None
        frame = pd.DataFrame([vars(item) for item in history]).set_index("timestamp")
        frame = ensure_ta(frame)
        latest = frame.iloc[-1]
        if int(latest["volume"]) < self.min_volume:
            return None
        if latest["rsi"] < 30 and latest["close"] > latest["vwap"]:
            return Signal(bar.symbol, "long", 0.7, self.name, "RSI oversold with price above VWAP", bar.timestamp)
        if latest["rsi"] > 70 and latest["close"] < latest["vwap"]:
            return Signal(bar.symbol, "short", 0.7, self.name, "RSI overbought with price below VWAP", bar.timestamp)
        if latest["macd_hist"] > 0 and latest["close"] > latest["bb_upper"]:
            return Signal(bar.symbol, "long", 0.6, self.name, "MACD breakout above Bollinger upper band", bar.timestamp)
        if latest["macd_hist"] < 0 and latest["close"] < latest["bb_lower"]:
            return Signal(bar.symbol, "short", 0.6, self.name, "MACD breakdown below Bollinger lower band", bar.timestamp)
        return None

    def on_news(self, event: NewsEvent) -> Optional[Signal]:
        if event.sentiment >= 1.0:
            return Signal(event.symbol, "long", 0.55, self.name, f"Positive news: {event.headline}", event.timestamp)
        if event.sentiment <= -1.0:
            return Signal(event.symbol, "short", 0.55, self.name, f"Negative news: {event.headline}", event.timestamp)
        return None

