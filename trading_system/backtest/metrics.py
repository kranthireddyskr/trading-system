from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from statistics import mean

import pandas as pd

from trading_system.storage.models import Trade


@dataclass
class PerformanceMetrics:
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration: int
    win_rate_pct: float
    average_win: float
    average_loss: float
    profit_factor: float
    expectancy_per_trade: float
    number_of_trades: int
    average_holding_period_minutes: float
    best_day: float
    worst_day: float
    monthly_returns: dict[str, float]

    def __repr__(self) -> str:
        return f"PerformanceMetrics(total_return_pct={self.total_return_pct:.2f}, sharpe_ratio={self.sharpe_ratio:.2f}, trades={self.number_of_trades})"

    @classmethod
    def calculate(cls, equity_curve: list[dict], trades: list[Trade], starting_capital: float) -> "PerformanceMetrics":
        frame = pd.DataFrame(equity_curve)
        if frame.empty:
            return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, {})
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.sort_values("timestamp")
        frame["returns"] = frame["equity"].pct_change().fillna(0.0)
        risk_free_daily = 0.045 / 252.0
        excess = frame["returns"] - risk_free_daily
        std = excess.std(ddof=0)
        downside = excess[excess < 0]
        sharpe = float((excess.mean() / std) * sqrt(252)) if std else 0.0
        sortino_std = downside.std(ddof=0)
        sortino = float((excess.mean() / sortino_std) * sqrt(252)) if sortino_std else 0.0
        ending = float(frame["equity"].iloc[-1])
        total_return_pct = ((ending / starting_capital) - 1.0) * 100 if starting_capital else 0.0
        total_days = max((frame["timestamp"].iloc[-1] - frame["timestamp"].iloc[0]).days, 1)
        annualized = (((ending / starting_capital) ** (365 / total_days)) - 1.0) * 100 if starting_capital else 0.0
        running_max = frame["equity"].cummax()
        drawdown = (frame["equity"] / running_max) - 1.0
        max_drawdown_pct = abs(float(drawdown.min()) * 100)
        drawdown_duration = int((drawdown < 0).astype(int).groupby((drawdown >= 0).astype(int).cumsum()).sum().max())
        calmar = (annualized / max_drawdown_pct) if max_drawdown_pct else 0.0
        wins = [trade.pnl for trade in trades if trade.pnl > 0]
        losses = [trade.pnl for trade in trades if trade.pnl <= 0]
        win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
        avg_hold = mean([((trade.exit_time - trade.entry_time).total_seconds() / 60.0) for trade in trades]) if trades else 0.0
        daily_returns = frame.set_index("timestamp")["equity"].resample("D").last().dropna().pct_change().dropna() * 100
        monthly_returns = (frame.set_index("timestamp")["equity"].resample("M").last().pct_change().dropna() * 100).to_dict()
        monthly_returns = {key.strftime("%Y-%m"): round(float(value), 2) for key, value in monthly_returns.items()}
        return cls(
            total_return_pct=round(total_return_pct, 2),
            annualized_return_pct=round(float(annualized), 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            calmar_ratio=round(float(calmar), 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            max_drawdown_duration=drawdown_duration,
            win_rate_pct=round(win_rate, 2),
            average_win=round(mean(wins), 2) if wins else 0.0,
            average_loss=round(mean(losses), 2) if losses else 0.0,
            profit_factor=round(sum(wins) / abs(sum(losses)), 2) if losses else 0.0,
            expectancy_per_trade=round(mean([trade.pnl for trade in trades]), 2) if trades else 0.0,
            number_of_trades=len(trades),
            average_holding_period_minutes=round(avg_hold, 2),
            best_day=round(float(daily_returns.max()), 2) if not daily_returns.empty else 0.0,
            worst_day=round(float(daily_returns.min()), 2) if not daily_returns.empty else 0.0,
            monthly_returns=monthly_returns,
        )

