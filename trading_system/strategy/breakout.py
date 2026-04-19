from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from trading_system.storage.models import MarketBar, NewsEvent, Signal
from trading_system.strategy.base import BaseStrategy
from trading_system.strategy.indicators import ensure_ta

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]


class BreakoutStrategy(BaseStrategy):
    """Volume-confirmed price breakout above recent highs / below recent lows.

    Long signal: close > N-bar rolling high AND volume > ``volume_mult`` × avg volume.
    Short signal: close < N-bar rolling low  AND volume > ``volume_mult`` × avg volume.

    ATR filter: the breakout candle's range must be > ``atr_mult`` × ATR to avoid
    noise-level moves.
    """

    name = "breakout"

    def __init__(self, lookback: int = 20, volume_mult: float = 1.5, atr_mult: float = 1.0) -> None:
        self.lookback = lookback
        self.volume_mult = volume_mult
        self.atr_mult = atr_mult
        self.warmup_periods = max(lookback, 14)
        self.params = {"lookback": float(lookback), "volume_mult": volume_mult, "atr_mult": atr_mult}
        self._bars: dict[str, list[MarketBar]] = defaultdict(list)
        self.logger = logging.getLogger("trading_system.strategy.breakout")

    def __repr__(self) -> str:
        return f"BreakoutStrategy(lookback={self.lookback}, volume_mult={self.volume_mult})"

    def on_bar(self, bar: MarketBar) -> Optional[Signal]:
        history = self._bars[bar.symbol]
        history.append(bar)
        history[:] = history[-max(self.lookback + 1, 60):]

        if len(history) < self.warmup_periods:
            return None

        try:
            frame = pd.DataFrame([vars(b) for b in history]).set_index("timestamp")
            frame = ensure_ta(frame)
        except Exception as exc:
            self.logger.warning("ensure_ta failed for %s: %s", bar.symbol, exc)
            return None

        latest = frame.iloc[-1]
        window = frame.iloc[-(self.lookback + 1):-1]  # exclude current bar

        rolling_high = float(window["high"].max())
        rolling_low = float(window["low"].min())
        avg_volume = float(window["volume"].mean())
        close = float(latest["close"])
        volume = float(latest["volume"])
        atr = float(latest.get("atr", (bar.high - bar.low)))
        candle_range = float(latest["high"]) - float(latest["low"])

        volume_ok = volume > self.volume_mult * avg_volume
        atr_ok = candle_range > self.atr_mult * max(atr, 0.01)

        if close > rolling_high and volume_ok and atr_ok:
            strength = round(min(0.75, 0.60 + (volume / max(avg_volume, 1) - self.volume_mult) * 0.03), 2)
            return Signal(
                bar.symbol, "long", strength, self.name,
                f"Breakout above {rolling_high:.2f} high with vol={volume:.0f} ({volume/max(avg_volume,1):.1f}×avg)",
                bar.timestamp,
            )

        if close < rolling_low and volume_ok and atr_ok:
            strength = round(min(0.75, 0.60 + (volume / max(avg_volume, 1) - self.volume_mult) * 0.03), 2)
            return Signal(
                bar.symbol, "short", strength, self.name,
                f"Breakdown below {rolling_low:.2f} low with vol={volume:.0f} ({volume/max(avg_volume,1):.1f}×avg)",
                bar.timestamp,
            )

        return None

    def on_news(self, event: NewsEvent) -> Optional[Signal]:
        return None
