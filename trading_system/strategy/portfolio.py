from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable, Optional

from trading_system.storage.models import MarketRegime, Signal, Trade
from trading_system.strategy.base import BaseStrategy


class MultiStrategyPortfolio:
    def __init__(self, strategies: list[BaseStrategy], weights: Optional[dict[str, float]] = None) -> None:
        self.strategies = strategies
        self.weights = weights or {strategy.name: 1.0 for strategy in strategies}
        self.performance: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=30))

    def __repr__(self) -> str:
        return f"MultiStrategyPortfolio(strategies={[strategy.name for strategy in self.strategies]!r})"

    def active_strategies(self, regime: MarketRegime) -> list[BaseStrategy]:
        active = []
        for strategy in self.strategies:
            if regime in {MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN} and strategy.name == "mean_reversion":
                continue
            if regime == MarketRegime.RANGING and strategy.name == "momentum":
                continue
            active.append(strategy)
        return active

    def aggregate(self, signals: Iterable[Signal]) -> list[Signal]:
        by_symbol: dict[str, list[Signal]] = defaultdict(list)
        for signal in signals:
            by_symbol[signal.symbol].append(signal)
        merged = []
        for symbol, items in by_symbol.items():
            direction_score = defaultdict(float)
            reasons = []
            for item in items:
                weight = self.weights.get(item.strategy, 1.0)
                direction_score[item.direction] += item.strength * weight
                reasons.append(f"{item.strategy}:{item.reason}")
            direction = max(direction_score, key=direction_score.get)
            strength = min(1.0, direction_score[direction] / max(len(items), 1))
            merged.append(Signal(symbol, direction, strength, "portfolio", " | ".join(reasons), items[-1].timestamp))
        return merged

    def update_attribution(self, trade: Trade) -> None:
        self.performance[trade.strategy].append(trade.pnl)
        if len(self.performance[trade.strategy]) < 5:
            return
        recent = list(self.performance[trade.strategy])
        avg = sum(recent) / len(recent)
        self.weights[trade.strategy] = max(0.2, min(2.0, 1.0 + (avg / 100.0)))
