from __future__ import annotations

import math


class PositionSizer:
    def __init__(self, fraction_kelly: float = 0.25, hard_cap_pct: float = 0.05) -> None:
        self.fraction_kelly = fraction_kelly
        self.hard_cap_pct = hard_cap_pct

    def __repr__(self) -> str:
        return f"PositionSizer(fraction_kelly={self.fraction_kelly}, hard_cap_pct={self.hard_cap_pct})"

    def size(self, capital: float, price: float, atr_value: float, win_rate: float, avg_win: float, avg_loss: float, multiplier: float = 1.0) -> float:
        if price <= 0 or atr_value <= 0 or avg_loss >= 0:
            max_notional = capital * self.hard_cap_pct * multiplier
            return round(max(0.0, max_notional / max(price, 0.01)), 2)
        payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 1.0
        kelly_fraction = max(0.0, win_rate - ((1.0 - win_rate) / max(payoff, 0.01)))
        kelly_fraction *= self.fraction_kelly
        risk_budget = capital * kelly_fraction * multiplier
        atr_adjusted = max(atr_value * price, 0.01)
        qty = risk_budget / atr_adjusted
        hard_cap_qty = (capital * self.hard_cap_pct * multiplier) / price
        return round(max(0.0, min(qty, hard_cap_qty)), 2)
