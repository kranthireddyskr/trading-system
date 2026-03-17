from __future__ import annotations

from collections import defaultdict
from typing import Optional

import pandas as pd

from trading_system.storage.models import MarketBar, NewsEvent, Signal
from trading_system.strategy.base import BaseStrategy
from trading_system.strategy.indicators import ensure_ta


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(self, lookback: int = 20, zscore_threshold: float = 2.0) -> None:
        self.lookback = lookback
        self.zscore_threshold = zscore_threshold
        self.params = {"lookback": float(lookback), "zscore_threshold": float(zscore_threshold)}
        self.warmup_periods = lookback
        self._bars: dict[str, list[MarketBar]] = defaultdict(list)

    def __repr__(self) -> str:
        return f"MeanReversionStrategy(lookback={self.lookback}, zscore_threshold={self.zscore_threshold})"

    def on_bar(self, bar: MarketBar) -> Optional[Signal]:
        history = self._bars[bar.symbol]
        history.append(bar)
        history[:] = history[-max(self.lookback, 50) :]
        if len(history) < self.warmup_periods:
            return None
        frame = pd.DataFrame([vars(item) for item in history]).set_index("timestamp")
        frame = ensure_ta(frame)
        latest = frame.iloc[-1]
        rolling_mean = frame["close"].rolling(self.lookback).mean().iloc[-1]
        rolling_std = frame["close"].rolling(self.lookback).std(ddof=0).iloc[-1]
        if not rolling_std or pd.isna(rolling_std):
            return None
        zscore = (latest["close"] - rolling_mean) / rolling_std
        atr_stop = latest["atr"]
        if zscore <= -self.zscore_threshold:
            return Signal(bar.symbol, "long", min(1.0, abs(float(zscore)) / 3.0), self.name, f"Z-score={zscore:.2f}, ATR={atr_stop:.2f}", bar.timestamp)
        if zscore >= self.zscore_threshold:
            return Signal(bar.symbol, "short", min(1.0, abs(float(zscore)) / 3.0), self.name, f"Z-score={zscore:.2f}, ATR={atr_stop:.2f}", bar.timestamp)
        if abs(zscore) < 0.25:
            return Signal(bar.symbol, "close", 0.5, self.name, "Price reverted to mean", bar.timestamp)
        return None

    def on_news(self, event: NewsEvent) -> Optional[Signal]:
        return None

