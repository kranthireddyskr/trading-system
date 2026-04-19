from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import requests

from trading_system.storage.models import MarketBar, NewsEvent, Signal
from trading_system.strategy.base import BaseStrategy


class EarningsMomentumStrategy(BaseStrategy):
    """Trade the post-earnings drift.

    Logic:
    - On a news event whose headline contains earnings keywords, score direction.
    - On subsequent bars for the same symbol, if we're within ``drift_window``
      bars of the earnings event and price keeps moving in the signal direction,
      emit a continuation signal.
    - Signals fade after ``drift_window`` bars.
    """

    name = "earnings_momentum"

    _BEAT_KEYWORDS = frozenset(["beat", "beats", "exceeded", "topped", "surpassed", "raised guidance", "record earnings", "record profit"])
    _MISS_KEYWORDS = frozenset(["miss", "missed", "fell short", "below estimates", "cut guidance", "warning", "lowered"])

    def __init__(self, drift_window: int = 10, min_strength: float = 0.55) -> None:
        self.drift_window = drift_window
        self.min_strength = min_strength
        self.warmup_periods = 1
        self.params = {"drift_window": float(drift_window), "min_strength": min_strength}
        # symbol → {"direction": str, "bars_remaining": int, "triggered_at": datetime}
        self._earnings_events: dict[str, dict] = {}
        self._bars: dict[str, list[MarketBar]] = defaultdict(list)
        self.logger = logging.getLogger("trading_system.strategy.earnings_momentum")

    def __repr__(self) -> str:
        return f"EarningsMomentumStrategy(drift_window={self.drift_window})"

    def on_bar(self, bar: MarketBar) -> Optional[Signal]:
        history = self._bars[bar.symbol]
        history.append(bar)
        history[:] = history[-60:]

        event = self._earnings_events.get(bar.symbol)
        if event is None:
            return None

        bars_remaining = event["bars_remaining"] - 1
        if bars_remaining <= 0:
            del self._earnings_events[bar.symbol]
            return None

        self._earnings_events[bar.symbol]["bars_remaining"] = bars_remaining
        direction = event["direction"]

        # Confirm continuation: price still moving in signal direction
        if len(history) >= 2:
            prev_close = history[-2].close
            if direction == "long" and bar.close <= prev_close:
                return None  # momentum stalled
            if direction == "short" and bar.close >= prev_close:
                return None

        strength = round(self.min_strength + (bars_remaining / self.drift_window) * 0.15, 2)
        return Signal(
            bar.symbol,
            direction,
            min(strength, 0.70),
            self.name,
            f"Post-earnings drift continuation (bars_left={bars_remaining})",
            bar.timestamp,
        )

    def on_news(self, event: NewsEvent) -> Optional[Signal]:
        headline = event.headline.lower()
        summary = (event.summary or "").lower()
        text = headline + " " + summary

        beat = any(kw in text for kw in self._BEAT_KEYWORDS)
        miss = any(kw in text for kw in self._MISS_KEYWORDS)

        if beat and not miss:
            direction = "long"
            strength = 0.70
            reason = f"Earnings beat: {event.headline[:80]}"
        elif miss and not beat:
            direction = "short"
            strength = 0.70
            reason = f"Earnings miss: {event.headline[:80]}"
        else:
            return None

        self._earnings_events[event.symbol] = {
            "direction": direction,
            "bars_remaining": self.drift_window,
            "triggered_at": event.timestamp,
        }
        self.logger.info("Earnings event registered for %s: %s (%s)", event.symbol, direction, event.headline[:60])
        return Signal(event.symbol, direction, strength, self.name, reason, event.timestamp)
