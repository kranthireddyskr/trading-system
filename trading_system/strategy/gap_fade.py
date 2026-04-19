from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from trading_system.storage.models import MarketBar, NewsEvent, Signal
from trading_system.strategy.base import BaseStrategy


class GapFadeStrategy(BaseStrategy):
    """Fade opening gaps that are likely to revert.

    A gap is identified by comparing the current bar's open to the previous
    bar's close.  If the gap is large (> ``min_gap_pct``) but the first bar
    closes back towards the prior close, we fade the gap.

    Long fade: today gapped DOWN, first bar closes well above its open
               → sell-off was over-done, fade back up.
    Short fade: today gapped UP, first bar closes well below its open
               → gap-up was over-done, fade back down.

    The signal is only emitted once per gap event (tracked per symbol).
    """

    name = "gap_fade"

    def __init__(self, min_gap_pct: float = 0.015, reversal_pct: float = 0.30) -> None:
        """
        Args:
            min_gap_pct:   Minimum gap size as a fraction of previous close (default 1.5%).
            reversal_pct:  The bar must retrace at least this fraction of the gap range
                           back toward prior close before we consider it a fade setup.
        """
        self.min_gap_pct = min_gap_pct
        self.reversal_pct = reversal_pct
        self.warmup_periods = 2
        self.params = {"min_gap_pct": min_gap_pct, "reversal_pct": reversal_pct}
        self._bars: dict[str, list[MarketBar]] = defaultdict(list)
        # Track which gaps we've already signalled so we don't spam
        self._gap_signalled: dict[str, str] = {}  # symbol → date string of signalled gap
        self.logger = logging.getLogger("trading_system.strategy.gap_fade")

    def __repr__(self) -> str:
        return f"GapFadeStrategy(min_gap_pct={self.min_gap_pct:.1%}, reversal_pct={self.reversal_pct:.1%})"

    def on_bar(self, bar: MarketBar) -> Optional[Signal]:
        history = self._bars[bar.symbol]
        history.append(bar)
        history[:] = history[-30:]

        if len(history) < 2:
            return None

        prev = history[-2]
        curr = history[-1]
        today_str = curr.timestamp.strftime("%Y-%m-%d")

        # Avoid signalling the same gap twice in a day
        if self._gap_signalled.get(bar.symbol) == today_str:
            return None

        prev_close = prev.close
        gap_pct = (curr.open - prev_close) / max(prev_close, 0.01)

        if abs(gap_pct) < self.min_gap_pct:
            return None

        gap_range = abs(curr.open - prev_close)

        if gap_pct < 0:
            # Gapped DOWN → fade if price reverses upward from the open
            retracement = curr.close - curr.open  # positive means rallied
            if retracement > self.reversal_pct * gap_range:
                self._gap_signalled[bar.symbol] = today_str
                strength = round(min(0.65, 0.50 + abs(gap_pct) * 5), 2)
                return Signal(
                    bar.symbol, "long", strength, self.name,
                    f"Gap-down fade: gap={gap_pct:.1%}, retracement={retracement:.2f}",
                    curr.timestamp,
                )

        else:
            # Gapped UP → fade if price reverses downward from the open
            retracement = curr.open - curr.close  # positive means sold off
            if retracement > self.reversal_pct * gap_range:
                self._gap_signalled[bar.symbol] = today_str
                strength = round(min(0.65, 0.50 + abs(gap_pct) * 5), 2)
                return Signal(
                    bar.symbol, "short", strength, self.name,
                    f"Gap-up fade: gap=+{gap_pct:.1%}, retracement={retracement:.2f}",
                    curr.timestamp,
                )

        return None

    def on_news(self, event: NewsEvent) -> Optional[Signal]:
        return None
