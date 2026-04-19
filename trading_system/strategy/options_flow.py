from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from trading_system.storage.models import MarketBar, NewsEvent, Signal
from trading_system.strategy.base import BaseStrategy


class OptionsFlowStrategy(BaseStrategy):
    """Placeholder: unusual options flow signal generator.

    Currently this is a stub that always returns ``None``.  When a live
    options-flow data feed is available (e.g. Unusual Whales, Market Chameleon
    or a brokerage API that surfaces unusual OI/volume), replace
    ``_fetch_options_flow()`` with a real implementation.

    The strategy architecture is in place:
      - ``on_bar`` calls ``_fetch_options_flow`` and interprets the result.
      - Bullish flow (heavy call buying relative to puts) → "long" signal.
      - Bearish flow (heavy put buying relative to calls) → "short" signal.
    """

    name = "options_flow"

    def __init__(self, call_put_threshold: float = 1.5) -> None:
        """
        Args:
            call_put_threshold: Minimum call/put volume ratio to consider unusual.
        """
        self.call_put_threshold = call_put_threshold
        self.warmup_periods = 1
        self.params = {"call_put_threshold": call_put_threshold}
        self._bars: dict[str, list[MarketBar]] = defaultdict(list)
        self.logger = logging.getLogger("trading_system.strategy.options_flow")

    def __repr__(self) -> str:
        return f"OptionsFlowStrategy(call_put_threshold={self.call_put_threshold})"

    def _fetch_options_flow(self, symbol: str) -> dict | None:
        """Stub: return None until a real feed is wired in.

        Expected return format when implemented::

            {
                "call_volume": int,
                "put_volume": int,
                "net_premium": float,   # positive = net call buying
                "unusual": bool,
            }
        """
        return None

    def on_bar(self, bar: MarketBar) -> Optional[Signal]:
        self._bars[bar.symbol].append(bar)
        self._bars[bar.symbol] = self._bars[bar.symbol][-60:]

        flow = self._fetch_options_flow(bar.symbol)
        if flow is None:
            return None

        call_vol = float(flow.get("call_volume", 0))
        put_vol = float(flow.get("put_volume", 0))
        unusual = bool(flow.get("unusual", False))

        if not unusual:
            return None

        if put_vol > 0 and call_vol / max(put_vol, 1) >= self.call_put_threshold:
            return Signal(
                bar.symbol, "long", 0.65, self.name,
                f"Unusual call flow: C/P={call_vol/max(put_vol,1):.1f}×",
                bar.timestamp,
            )

        if call_vol > 0 and put_vol / max(call_vol, 1) >= self.call_put_threshold:
            return Signal(
                bar.symbol, "short", 0.65, self.name,
                f"Unusual put flow: P/C={put_vol/max(call_vol,1):.1f}×",
                bar.timestamp,
            )

        return None

    def on_news(self, event: NewsEvent) -> Optional[Signal]:
        return None
