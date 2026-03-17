from __future__ import annotations

from typing import Iterable

import pandas as pd

from trading_system.storage.models import MarketBar, Position


class CorrelationChecker:
    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    def __repr__(self) -> str:
        return f"CorrelationChecker(threshold={self.threshold})"

    def is_allowed(self, symbol: str, positions: list[Position], bar_history: dict[str, list[MarketBar]]) -> bool:
        if not positions:
            return True
        target_bars = bar_history.get(symbol, [])
        if len(target_bars) < 20:
            return True
        target_series = pd.Series([bar.close for bar in target_bars[-20:]])
        for position in positions:
            other_bars = bar_history.get(position.symbol, [])
            if len(other_bars) < 20:
                continue
            other_series = pd.Series([bar.close for bar in other_bars[-20:]])
            correlation = float(target_series.pct_change().corr(other_series.pct_change()))
            if pd.notna(correlation) and abs(correlation) > self.threshold:
                return False
        return True

