from __future__ import annotations

import math

from trading_system.config import RiskConfig
from trading_system.models import AccountSnapshot, RiskDecision


class RiskManager(object):
    def __init__(self, config):
        self.config = config
        self.trades_today = 0
        self.halted = False
        self.halt_reason = ""

    def can_enter(self, signal, account, open_positions):
        if self.halted:
            return RiskDecision(False, "halted:%s" % self.halt_reason, 0)
        if self.trades_today >= self.config.max_trades_per_day:
            return RiskDecision(False, "daily_trade_limit", 0)
        if open_positions >= self.config.max_open_positions:
            return RiskDecision(False, "max_open_positions", 0)
        daily_drawdown = max(0.0, account.daily_start_equity - account.equity)
        if daily_drawdown >= account.daily_start_equity * self.config.max_daily_loss_pct:
            return RiskDecision(False, "daily_loss_limit", 0)

        risk_capital = account.equity * self.config.risk_per_trade_pct
        risk_per_share = max(signal.price * self.config.stop_loss_pct, 0.01)
        max_by_risk = int(math.floor(risk_capital / risk_per_share))
        max_position_value = account.equity * self.config.max_position_notional_pct
        max_by_notional = int(math.floor(max_position_value / signal.price))
        max_by_cash = int(math.floor(account.buying_power / signal.price))
        quantity = max(0, min(max_by_risk, max_by_notional, max_by_cash))
        if quantity <= 0:
            return RiskDecision(False, "insufficient_buying_power", 0)

        return RiskDecision(
            True,
            "approved",
            quantity,
            stop_loss=signal.price * (1 - self.config.stop_loss_pct),
            take_profit=signal.price * (1 + self.config.take_profit_pct),
        )

    def on_fill(self):
        self.trades_today += 1

    def halt(self, reason):
        self.halted = True
        self.halt_reason = reason

