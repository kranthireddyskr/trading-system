from __future__ import annotations

from dataclasses import dataclass

from trading_system.storage.models import Position, Signal


@dataclass
class RiskLimits:
    max_positions: int = 10
    max_position_pct: float = 0.05
    max_sector_pct: float = 0.20
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10
    max_trades_per_day: int = 20
    min_price: float = 5.0
    min_volume: int = 500000

    def __repr__(self) -> str:
        return f"RiskLimits(max_positions={self.max_positions}, max_position_pct={self.max_position_pct}, max_drawdown_pct={self.max_drawdown_pct})"

