from __future__ import annotations

from collections import defaultdict

import pandas as pd

from trading_system.storage.models import MarketBar, MarketRegime
from trading_system.strategy.indicators import ensure_ta


class MarketRegimeDetector:
    def __init__(self) -> None:
        self._bars: dict[str, list[MarketBar]] = defaultdict(list)

    def __repr__(self) -> str:
        return "MarketRegimeDetector()"

    def on_bar(self, bar: MarketBar) -> None:
        bars = self._bars[bar.symbol]
        bars.append(bar)
        bars[:] = bars[-300:]

    def detect(self, symbol: str) -> MarketRegime:
        bars = self._bars.get(symbol, [])
        if len(bars) < 200:
            return MarketRegime.UNKNOWN
        frame = pd.DataFrame([vars(item) for item in bars]).set_index("timestamp")
        frame = ensure_ta(frame)
        latest = frame.iloc[-1]
        ma50 = frame["close"].rolling(50).mean().iloc[-1]
        ma200 = frame["close"].rolling(200).mean().iloc[-1]
        realized_vol = frame["close"].pct_change().rolling(20).std().iloc[-1] * (252 ** 0.5)
        if realized_vol > 0.25:
            return MarketRegime.HIGH_VOLATILITY
        if latest["close"] > ma50 > ma200 and latest["adx"] > 25:
            return MarketRegime.TRENDING_UP
        if latest["close"] < ma50 < ma200 and latest["adx"] > 25:
            return MarketRegime.TRENDING_DOWN
        if latest["adx"] < 20:
            return MarketRegime.RANGING
        return MarketRegime.UNKNOWN

