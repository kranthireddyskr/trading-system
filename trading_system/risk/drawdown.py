from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class DrawdownState:
    peak_equity: float = 0.0
    current_drawdown_pct: float = 0.0
    consecutive_losses: int = 0
    trading_halted: bool = False
    daily_start_equity: float = 0.0
    current_day: date | None = None

    def __repr__(self) -> str:
        return (
            f"DrawdownState(peak_equity={self.peak_equity:.2f}, current_drawdown_pct={self.current_drawdown_pct:.2f}, "
            f"consecutive_losses={self.consecutive_losses}, trading_halted={self.trading_halted})"
        )


class DrawdownMonitor:
    def __init__(self, soft_limit: float = 0.05, hard_limit: float = 0.10) -> None:
        self.soft_limit = soft_limit
        self.hard_limit = hard_limit
        self.state = DrawdownState()

    def __repr__(self) -> str:
        return f"DrawdownMonitor(soft_limit={self.soft_limit}, hard_limit={self.hard_limit})"

    def update_equity(self, timestamp: datetime, equity: float) -> DrawdownState:
        equity = round(float(equity), 2)
        if self.state.current_day != timestamp.date():
            self.state.current_day = timestamp.date()
            self.state.daily_start_equity = equity
            self.state.consecutive_losses = 0
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity
        peak = max(self.state.peak_equity, 1.0)
        self.state.current_drawdown_pct = round((peak - equity) / peak, 4)
        if self.state.current_drawdown_pct >= self.hard_limit or self.state.consecutive_losses >= 3:
            self.state.trading_halted = True
        return self.state

    def record_trade_result(self, pnl: float) -> DrawdownState:
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        if self.state.consecutive_losses >= 3:
            self.state.trading_halted = True
        return self.state

    def size_multiplier(self) -> float:
        if self.state.current_drawdown_pct >= self.soft_limit:
            return 0.5
        return 1.0

