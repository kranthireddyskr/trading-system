from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from trading_system.backtest.metrics import PerformanceMetrics
from trading_system.execution.order_manager import OrderManager
from trading_system.execution.paper import PaperBroker
from trading_system.risk.correlation import CorrelationChecker
from trading_system.risk.drawdown import DrawdownMonitor
from trading_system.risk.limits import RiskLimits
from trading_system.risk.position_sizer import PositionSizer
from trading_system.storage.models import MarketBar, Position, Signal, Trade


@dataclass
class BacktestResult:
    metrics: PerformanceMetrics
    trades: list[Trade]
    equity_curve: list[dict]

    def __repr__(self) -> str:
        return f"BacktestResult(trades={len(self.trades)}, sharpe={self.metrics.sharpe_ratio:.2f})"


class BacktestEngine:
    def __init__(self, starting_capital: float = 100000.0, slippage_pct: float = 0.0005, commission: float = 0.0) -> None:
        self.starting_capital = starting_capital
        self.paper_broker = PaperBroker(slippage_pct=slippage_pct, commission=commission)
        self.order_manager = OrderManager(self.paper_broker)
        self.position_sizer = PositionSizer()
        self.risk_limits = RiskLimits()
        self.drawdown_monitor = DrawdownMonitor()
        self.correlation_checker = CorrelationChecker()

    def __repr__(self) -> str:
        return f"BacktestEngine(starting_capital={self.starting_capital}, slippage_pct={self.paper_broker.slippage_pct})"

    def run(self, data_by_symbol: dict[str, pd.DataFrame], strategies: list, portfolio) -> BacktestResult:
        cash = float(self.starting_capital)
        positions: dict[str, Position] = {}
        trades: list[Trade] = []
        equity_curve: list[dict] = []
        bar_history: dict[str, list[MarketBar]] = {symbol: [] for symbol in data_by_symbol}
        timeline = sorted({timestamp for frame in data_by_symbol.values() for timestamp in frame.index})

        for timestamp in timeline:
            generated_signals: list[Signal] = []
            for symbol, frame in data_by_symbol.items():
                if timestamp not in frame.index:
                    continue
                row = frame.loc[timestamp]
                bar = MarketBar(symbol, timestamp.to_pydatetime(), row["open"], row["high"], row["low"], row["close"], int(row["volume"]), row.get("vwap", row["close"]), "historical")
                bar_history[symbol].append(bar)
                for strategy in strategies:
                    signal = strategy.on_bar(bar)
                    if signal is not None:
                        generated_signals.append(signal)
                position = positions.get(symbol)
                if position:
                    if position.side == "long" and (bar.low <= (position.stop_loss or 0) or bar.high >= (position.take_profit or 10 ** 9)):
                        order = self.order_manager.submit(symbol=symbol, side="sell", qty=position.qty, order_type="market", strategy=position.strategy)
                        fill = self.order_manager.fill_order(order, bar.close)
                        if fill is not None:
                            pnl = round((fill.fill_price - position.entry_price) * position.qty, 2)
                            trade = Trade(symbol, "long", position.opened_at, bar.timestamp, position.entry_price, fill.fill_price, position.qty, pnl, position.strategy)
                            trades.append(trade)
                            portfolio.update_attribution(trade)
                            cash += round(fill.fill_price * position.qty, 2)
                            self.drawdown_monitor.record_trade_result(pnl)
                            del positions[symbol]

            account_equity = cash + sum(bar_history[symbol][-1].close * position.qty for symbol, position in positions.items() if bar_history[symbol])
            drawdown_state = self.drawdown_monitor.update_equity(timestamp.to_pydatetime(), account_equity)
            equity_curve.append({
                "timestamp": timestamp.to_pydatetime(),
                "equity": round(account_equity, 2),
                "cash": round(cash, 2),
                "drawdown": round(drawdown_state.current_drawdown_pct * 100, 2),
            })
            if drawdown_state.trading_halted:
                break

            for signal in portfolio.aggregate(generated_signals):
                if signal.direction == "close":
                    continue
                if signal.symbol in positions:
                    continue
                latest_bar = bar_history[signal.symbol][-1]
                if latest_bar.close < self.risk_limits.min_price or latest_bar.volume < self.risk_limits.min_volume:
                    continue
                if len(positions) >= self.risk_limits.max_positions:
                    continue
                if not self.correlation_checker.is_allowed(signal.symbol, list(positions.values()), bar_history):
                    continue
                win_rate = len([trade for trade in trades if trade.pnl > 0]) / len(trades) if trades else 0.5
                avg_win = sum(trade.pnl for trade in trades if trade.pnl > 0) / len([trade for trade in trades if trade.pnl > 0]) if any(trade.pnl > 0 for trade in trades) else 100.0
                avg_loss = sum(trade.pnl for trade in trades if trade.pnl <= 0) / len([trade for trade in trades if trade.pnl <= 0]) if any(trade.pnl <= 0 for trade in trades) else -50.0
                qty = self.position_sizer.size(cash, latest_bar.close, max(latest_bar.vwap / max(latest_bar.close, 0.01), 0.01), win_rate, avg_win, avg_loss, self.drawdown_monitor.size_multiplier())
                if qty <= 0:
                    continue
                order = self.order_manager.submit(symbol=signal.symbol, side="buy" if signal.direction == "long" else "sell", qty=qty, order_type="market", strategy=signal.strategy)
                fill = self.order_manager.fill_order(order, latest_bar.close)
                if fill is None:
                    continue
                cash -= round(fill.fill_price * qty, 2)
                positions[signal.symbol] = Position(
                    symbol=signal.symbol,
                    side=signal.direction,
                    qty=qty,
                    entry_price=fill.fill_price,
                    opened_at=signal.timestamp,
                    strategy=signal.strategy,
                    stop_loss=round(fill.fill_price * (0.98 if signal.direction == "long" else 1.02), 2),
                    take_profit=round(fill.fill_price * (1.03 if signal.direction == "long" else 0.97), 2),
                )

        metrics = PerformanceMetrics.calculate(equity_curve, trades, self.starting_capital)
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)
