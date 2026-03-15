from __future__ import annotations

import time
from collections import defaultdict

from trading_system.analytics import compute_performance_metrics
from trading_system.models import AccountSnapshot, ClosedTrade, Position


class TradingEngine(object):
    def __init__(self, strategy, risk_manager, execution_engine, storage, broker_client=None, monitor=None):
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.execution_engine = execution_engine
        self.storage = storage
        self.broker_client = broker_client
        self.monitor = monitor
        self.bars_by_symbol = defaultdict(list)
        self.news_by_symbol = defaultdict(list)
        self.positions = {}
        self.closed_trades = []
        self.equity_curve = []
        self.daily_start_equity = 0.0
        self.cash = 25000.0
        self.buying_power = 25000.0
        self.current_day = None

    def ingest_bar(self, bar):
        self.bars_by_symbol[bar.symbol].append(bar)
        self.storage.store_bar(bar)

    def ingest_news(self, news):
        if any(existing.event_id == news.event_id for existing in self.news_by_symbol[news.symbol]):
            return
        self.news_by_symbol[news.symbol].append(news)
        self.storage.store_news(news)

    def build_account_snapshot(self, timestamp):
        if self.current_day != timestamp.date():
            self.current_day = timestamp.date()
            if self.daily_start_equity <= 0:
                self.daily_start_equity = self.cash
            else:
                self.daily_start_equity = self.cash + sum(
                    self.positions[symbol].quantity * self.bars_by_symbol[symbol][-1].close
                    for symbol in self.positions
                    if self.bars_by_symbol.get(symbol)
                )
            self.risk_manager.trades_today = 0
        equity = self.cash
        gross_exposure = 0.0
        for symbol, position in self.positions.items():
            latest_bar = self.bars_by_symbol[symbol][-1]
            position_value = position.quantity * latest_bar.close
            equity += position_value
            gross_exposure += position_value
        if self.daily_start_equity <= 0:
            self.daily_start_equity = equity
        snapshot = AccountSnapshot(
            timestamp=timestamp,
            equity=equity,
            cash=self.cash,
            buying_power=self.buying_power,
            daily_start_equity=self.daily_start_equity,
            open_positions=len(self.positions),
            gross_exposure=gross_exposure,
        )
        return snapshot

    def record_equity(self, timestamp):
        snapshot = self.build_account_snapshot(timestamp)
        point = {
            "timestamp": timestamp,
            "equity": snapshot.equity,
            "cash": snapshot.cash,
            "gross_exposure": snapshot.gross_exposure,
        }
        self.equity_curve.append(point)
        if self.monitor is not None:
            self.monitor.dashboard({
                "equity": snapshot.equity,
                "cash": snapshot.cash,
                "gross_exposure": snapshot.gross_exposure,
                "open_positions": len(self.positions),
                "closed_trades": len(self.closed_trades),
            })
            self.monitor.heartbeat("alive", {
                "equity": snapshot.equity,
                "open_positions": len(self.positions),
            })
        return snapshot

    def evaluate_entries(self, timestamp):
        signals = self.strategy.generate_signals(self.bars_by_symbol, self.news_by_symbol, timestamp)
        account = self.build_account_snapshot(timestamp)
        for signal in signals:
            self.storage.store_signal(signal)
            if signal.symbol in self.positions:
                continue
            decision = self.risk_manager.can_enter(signal, account, len(self.positions))
            if not decision.allowed:
                self.storage.store_system_event("signal_rejected", {
                    "symbol": signal.symbol,
                    "reason": decision.reason,
                    "score": signal.score,
                })
                continue
            fill = self.execution_engine.execute(signal.symbol, signal.side, decision.quantity, signal.price)
            self.risk_manager.on_fill()
            self.positions[signal.symbol] = Position(
                symbol=signal.symbol,
                entry_time=timestamp,
                entry_price=fill.fill_price,
                quantity=decision.quantity,
                stop_loss=decision.stop_loss,
                take_profit=decision.take_profit,
                broker_order_id=fill.order_id,
            )
            self.cash -= fill.fill_price * fill.quantity + fill.commission
            self.buying_power = self.cash
            self.storage.store_fill(fill)

    def evaluate_exits(self, timestamp):
        for symbol in list(self.positions.keys()):
            position = self.positions[symbol]
            bars = self.bars_by_symbol.get(symbol, [])
            if not bars:
                continue
            reason = self.strategy.should_exit(position, bars, timestamp)
            if reason is None:
                continue
            latest_bar = bars[-1]
            fill = self.execution_engine.execute(symbol, "SELL", position.quantity, latest_bar.close)
            pnl = (fill.fill_price - position.entry_price) * position.quantity - fill.commission
            trade = ClosedTrade(
                symbol=symbol,
                side=position.side,
                entry_time=position.entry_time,
                exit_time=timestamp,
                entry_price=position.entry_price,
                exit_price=fill.fill_price,
                quantity=position.quantity,
                pnl=pnl,
                reason=reason,
                entry_order_id=position.broker_order_id,
                exit_order_id=fill.order_id,
            )
            self.cash += fill.fill_price * fill.quantity - fill.commission
            self.buying_power = self.cash
            self.storage.store_fill(fill)
            self.storage.store_trade(trade)
            self.closed_trades.append(trade)
            del self.positions[symbol]

    def run_backtest(self, grouped_bars, poll_seconds=0.0):
        for timestamp, bundle in grouped_bars:
            for bar in bundle:
                self.ingest_bar(bar)
            self.evaluate_exits(timestamp)
            self.evaluate_entries(timestamp)
            self.record_equity(timestamp)
            if poll_seconds > 0:
                time.sleep(poll_seconds)
        return self.summary()

    def summary(self):
        metrics = compute_performance_metrics(self.equity_curve, self.closed_trades)
        metrics["cash"] = round(self.cash, 2)
        metrics["open_positions"] = len(self.positions)
        return metrics
