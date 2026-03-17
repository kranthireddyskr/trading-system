from __future__ import annotations

import logging
import queue
import signal
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from trading_system.config.settings import Settings
from trading_system.data.feeds import AlpacaWebSocketFeed
from trading_system.data.universe import SymbolUniverse
from trading_system.execution.alpaca import AlpacaBroker
from trading_system.execution.order_manager import OrderManager
from trading_system.execution.paper import PaperBroker
from trading_system.monitoring.alerts import AlertManager
from trading_system.monitoring.dashboard import DashboardServer
from trading_system.monitoring.heartbeat import Heartbeat
from trading_system.risk.correlation import CorrelationChecker
from trading_system.risk.drawdown import DrawdownMonitor
from trading_system.risk.limits import RiskLimits
from trading_system.risk.position_sizer import PositionSizer
from trading_system.storage.file_storage import FileStorage
from trading_system.storage.models import Fill, MarketBar, NewsEvent, Position, Signal, SystemEvent, Trade
from trading_system.storage.timescale import TimescaleDBWriter
from trading_system.strategy.mean_reversion import MeanReversionStrategy
from trading_system.strategy.ml_signal import MLSignalStrategy
from trading_system.strategy.momentum import MomentumStrategy
from trading_system.strategy.portfolio import MultiStrategyPortfolio
from trading_system.strategy.regime import MarketRegimeDetector


class TradingAgent:
    def __init__(self, settings: Settings, output_dir: Path, watchlist_path: Path, dry_run: bool = False, paper: bool = True, dashboard_port: int = 8080) -> None:
        self.settings = settings
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._build_logger()
        self.file_storage = FileStorage(self.output_dir)
        self.db_writer = TimescaleDBWriter(settings.storage_dsn, self.file_storage, settings.flush_interval_seconds)
        self.db_writer.write_schema_file(self.output_dir / "timescale_schema.sql")
        self.alert_manager = AlertManager(settings)
        self.heartbeat = Heartbeat(self.output_dir / "heartbeat.json")
        self.state: dict[str, object] = {"metrics": {}, "positions": [], "trades": [], "signals": [], "equity": []}
        self.dashboard = DashboardServer(self._dashboard_state, port=dashboard_port)
        self.universe = SymbolUniverse(watchlist_path, settings.apca_api_key_id, settings.apca_api_secret_key)
        self.bar_queue: queue.Queue[MarketBar] = queue.Queue()
        self.feed = AlpacaWebSocketFeed(settings.apca_api_key_id, settings.apca_api_secret_key, self.universe.symbols(), self.bar_queue, self.logger)
        self.broker = PaperBroker() if dry_run else AlpacaBroker(settings, paper=paper)
        self.order_manager = OrderManager(self.broker)
        self.position_sizer = PositionSizer()
        self.risk_limits = RiskLimits()
        self.drawdown = DrawdownMonitor()
        self.correlation = CorrelationChecker()
        self.regime_detector = MarketRegimeDetector()
        self.strategies = [
            MomentumStrategy(),
            MeanReversionStrategy(),
            MLSignalStrategy(self.output_dir / "models"),
        ]
        self.portfolio = MultiStrategyPortfolio(self.strategies)
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.signals: deque[Signal] = deque(maxlen=100)
        self.bar_history: dict[str, list[MarketBar]] = defaultdict(list)
        self.cash = 100000.0
        self.buying_power = 100000.0
        self.running = True
        self.dashboard_started = False
        self._register_signals()

    def __repr__(self) -> str:
        return f"TradingAgent(output_dir={str(self.output_dir)!r}, positions={len(self.positions)}, trades={len(self.trades)})"

    def _build_logger(self) -> logging.Logger:
        logger = logging.getLogger("trading_system")
        logger.setLevel(getattr(logging, self.settings.log_level.upper(), logging.INFO))
        logger.handlers.clear()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        file_handler = RotatingFileHandler(self.output_dir / "trading.log", maxBytes=1_000_000, backupCount=5)
        file_handler.setFormatter(formatter)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        return logger

    def _register_signals(self) -> None:
        def handle_shutdown(signum, frame) -> None:
            self.logger.info("Received shutdown signal %s", signum)
            self.running = False

        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGINT, handle_shutdown)

    def _dashboard_state(self) -> dict:
        return self.state

    def market_is_open(self, now: datetime) -> bool:
        eastern = now.astimezone(ZoneInfo(self.settings.timezone))
        if eastern.weekday() >= 5:
            return False
        open_time = eastern.replace(hour=9, minute=30, second=0, microsecond=0)
        close_time = eastern.replace(hour=16, minute=0, second=0, microsecond=0)
        return open_time <= eastern <= close_time

    def fetch_news(self, symbols: list[str]) -> list[NewsEvent]:
        headers = {
            "APCA-API-KEY-ID": self.settings.apca_api_key_id,
            "APCA-API-SECRET-KEY": self.settings.apca_api_secret_key,
        }
        try:
            response = requests.get(
                "https://data.alpaca.markets/v1beta1/news",
                headers=headers,
                params={"symbols": ",".join(symbols), "limit": 20, "sort": "desc"},
                timeout=20,
            )
            response.raise_for_status()
            news_events = []
            for item in response.json().get("news", []):
                timestamp = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                sentiment = 1.0 if "beat" in item.get("headline", "").lower() else (-1.0 if "miss" in item.get("headline", "").lower() else 0.0)
                for symbol in item.get("symbols", []):
                    news_events.append(NewsEvent(symbol, item.get("headline", ""), item.get("summary", ""), timestamp, sentiment, "alpaca_news"))
            return news_events
        except Exception:
            return []

    def start_background_services(self) -> None:
        if not self.dashboard_started:
            self.dashboard.start()
            self.dashboard_started = True
        self.feed.start()
        self.reconcile_broker_state()

    def _log_event(self, level: str, message: str, payload: dict | None = None) -> None:
        payload = payload or {}
        event = SystemEvent(level=level, message=message, timestamp=datetime.utcnow(), payload=payload)
        self.db_writer.write_event(event)
        getattr(self.logger, level.lower(), self.logger.info)(message)

    def _record_bar(self, bar: MarketBar) -> None:
        self.bar_history[bar.symbol].append(bar)
        self.bar_history[bar.symbol] = self.bar_history[bar.symbol][-300:]
        self.regime_detector.on_bar(bar)
        self.db_writer.write_bar(bar)

    def _record_signal(self, signal: Signal) -> None:
        self.signals.append(signal)
        self.db_writer.write_signal(signal)

    def _record_trade(self, trade: Trade) -> None:
        self.trades.append(trade)
        self.db_writer.write_trade(trade)
        self.drawdown.record_trade_result(trade.pnl)
        self.portfolio.update_attribution(trade)

    def reconcile_broker_state(self) -> None:
        if isinstance(self.broker, PaperBroker):
            return
        try:
            account = self.broker.get_account()
            self.cash = round(float(account.get("cash", self.cash)), 2)
            self.buying_power = round(float(account.get("buying_power", self.buying_power)), 2)
            broker_positions = self.broker.get_positions()
            self.positions.clear()
            for item in broker_positions:
                symbol = str(item.get("symbol"))
                qty = abs(float(item.get("qty", 0.0)))
                side = "long" if float(item.get("qty", 0.0)) >= 0 else "short"
                entry_price = round(float(item.get("avg_entry_price", 0.0)), 2)
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    entry_price=entry_price,
                    opened_at=datetime.utcnow(),
                    strategy="reconciled",
                    stop_loss=round(entry_price * (0.98 if side == "long" else 1.02), 2),
                    take_profit=round(entry_price * (1.03 if side == "long" else 0.97), 2),
                    broker_order_id=str(item.get("asset_id", "")),
                )
            open_orders = self.broker.get_orders()
            for payload in open_orders:
                status = str(payload.get("status", ""))
                if status in {"new", "accepted", "partially_filled"}:
                    order = Order(
                        order_id=str(payload.get("id")),
                        symbol=str(payload.get("symbol")),
                        side=str(payload.get("side")),
                        qty=float(payload.get("qty", 0.0)),
                        order_type=str(payload.get("type", "market")),
                        submitted_at=datetime.fromisoformat(str(payload.get("created_at")).replace("Z", "+00:00")) if payload.get("created_at") else datetime.utcnow(),
                        limit_price=payload.get("limit_price"),
                        stop_price=payload.get("stop_price"),
                        take_profit_price=None,
                        status=status,
                        strategy="reconciled",
                    )
                    self.order_manager.active_orders[order.order_id] = order
            self._log_event("info", "Broker state reconciled", {"positions": len(self.positions), "open_orders": len(self.order_manager.active_orders)})
        except Exception as exc:
            self._log_event("warning", "Broker reconciliation failed", {"error": str(exc)})

    def _mark_to_market_equity(self) -> float:
        equity = self.cash
        for symbol, position in self.positions.items():
            if self.bar_history[symbol]:
                price = self.bar_history[symbol][-1].close
                direction = 1 if position.side == "long" else -1
                equity += round(position.qty * (position.entry_price + ((price - position.entry_price) * direction)), 2)
        return round(equity, 2)

    def _update_dashboard_state(self, now: datetime, regime_map: dict[str, str]) -> None:
        equity = self._mark_to_market_equity()
        drawdown_state = self.drawdown.update_equity(now, equity)
        metrics = {
            "equity": equity,
            "cash": round(self.cash, 2),
            "positions": len(self.positions),
            "win_rate": round((len([trade for trade in self.trades if trade.pnl > 0]) / len(self.trades) * 100), 2) if self.trades else 0.0,
            "daily_pnl": round(equity - max(self.drawdown.state.daily_start_equity, 100000.0), 2),
            "drawdown_pct": round(drawdown_state.current_drawdown_pct * 100, 2),
            "circuit_breaker": drawdown_state.trading_halted,
            "regime": regime_map,
        }
        self.state["metrics"] = metrics
        self.state["positions"] = [position.__dict__ for position in self.positions.values()]
        self.state["trades"] = [trade.__dict__ for trade in self.trades[-20:]]
        self.state["signals"] = [signal.__dict__ for signal in list(self.signals)[-20:]]
        equity_points = self.state.setdefault("equity", [])
        equity_points.append({"timestamp": now.isoformat(), "equity": equity, "cash": round(self.cash, 2), "drawdown": round(drawdown_state.current_drawdown_pct * 100, 2)})
        self.state["equity"] = equity_points[-500:]
        self.heartbeat.write("ok", metrics)
        self.db_writer.write_metrics(now, metrics)

    def _handle_existing_positions(self, bar: MarketBar) -> None:
        position = self.positions.get(bar.symbol)
        if position is None:
            return
        should_close = False
        if position.side == "long":
            should_close = bool((position.stop_loss and bar.low <= position.stop_loss) or (position.take_profit and bar.high >= position.take_profit))
        elif position.side == "short":
            should_close = bool((position.stop_loss and bar.high >= position.stop_loss) or (position.take_profit and bar.low <= position.take_profit))
        if not should_close:
            return
        order = self.order_manager.submit(symbol=bar.symbol, side="sell" if position.side == "long" else "buy", qty=position.qty, order_type="market", strategy=position.strategy)
        fill = self.order_manager.fill_order(order, bar.close)
        if fill is None:
            fill = Fill(order.order_id, bar.symbol, order.side, position.qty, bar.close, bar.close, 0.0, 0.0, datetime.utcnow())
        direction = 1 if position.side == "long" else -1
        pnl = round((fill.fill_price - position.entry_price) * position.qty * direction, 2)
        trade = Trade(bar.symbol, position.side, position.opened_at, bar.timestamp, position.entry_price, fill.fill_price, position.qty, pnl, position.strategy)
        self.cash += round(fill.fill_price * position.qty, 2)
        self.db_writer.write_fill(fill)
        self._record_trade(trade)
        del self.positions[bar.symbol]

    def _apply_broker_fills(self, fills: list[Fill], market_prices: dict[str, float]) -> None:
        for fill in fills:
            self.db_writer.write_fill(fill)
            side = fill.side.lower()
            existing = self.positions.get(fill.symbol)
            if existing is None and side in {"buy", "long"}:
                stop_loss = round(fill.fill_price * 0.98, 2)
                take_profit = round(fill.fill_price * 1.03, 2)
                self.cash -= round(fill.fill_price * fill.qty, 2)
                self.positions[fill.symbol] = Position(
                    symbol=fill.symbol,
                    side="long",
                    qty=fill.qty,
                    entry_price=fill.fill_price,
                    opened_at=fill.timestamp,
                    strategy="broker_sync",
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    broker_order_id=fill.order_id,
                )
                continue
            if existing is not None and side in {"sell", "short", "buy"}:
                direction = 1 if existing.side == "long" else -1
                pnl = round((fill.fill_price - existing.entry_price) * fill.qty * direction, 2)
                trade = Trade(fill.symbol, existing.side, existing.opened_at, fill.timestamp, existing.entry_price, fill.fill_price, fill.qty, pnl, existing.strategy)
                self.cash += round(fill.fill_price * fill.qty, 2)
                self._record_trade(trade)
                self.positions.pop(fill.symbol, None)

    def _open_position(self, signal: Signal, bar: MarketBar, regime_label: str) -> None:
        if signal.symbol in self.positions:
            return
        if len(self.positions) >= self.risk_limits.max_positions:
            return
        if not self.correlation.is_allowed(signal.symbol, list(self.positions.values()), self.bar_history):
            return
        if bar.close < self.risk_limits.min_price or bar.volume < self.risk_limits.min_volume:
            return
        win_rate = len([trade for trade in self.trades if trade.pnl > 0]) / len(self.trades) if self.trades else 0.5
        avg_win = sum(trade.pnl for trade in self.trades if trade.pnl > 0) / len([trade for trade in self.trades if trade.pnl > 0]) if any(trade.pnl > 0 for trade in self.trades) else 100.0
        avg_loss = sum(trade.pnl for trade in self.trades if trade.pnl <= 0) / len([trade for trade in self.trades if trade.pnl <= 0]) if any(trade.pnl <= 0 for trade in self.trades) else -50.0
        atr_like = max(abs((bar.high - bar.low) / max(bar.close, 0.01)), 0.01)
        multiplier = self.drawdown.size_multiplier()
        if regime_label == "HIGH_VOLATILITY":
            multiplier *= 0.5
        qty = self.position_sizer.size(self.cash, bar.close, atr_like, win_rate, avg_win, avg_loss, multiplier)
        if qty <= 0:
            return
        order = self.order_manager.submit(
            symbol=signal.symbol,
            side="buy" if signal.direction == "long" else "sell",
            qty=qty,
            order_type="market",
            strategy=signal.strategy,
            stop_loss_price=round(bar.close * (0.98 if signal.direction == "long" else 1.02), 2),
            take_profit_price=round(bar.close * (1.03 if signal.direction == "long" else 0.97), 2),
        )
        fill = self.order_manager.fill_order(order, bar.close)
        if fill is None:
            fill = Fill(order.order_id, signal.symbol, order.side, qty, bar.close, bar.close, 0.0, 0.0, datetime.utcnow())
            self._log_event("warning", "Using synthetic fill for broker order tracking", {"order_id": order.order_id})
        self.db_writer.write_fill(fill)
        self.cash -= round(fill.fill_price * qty, 2)
        self.positions[signal.symbol] = Position(
            symbol=signal.symbol,
            side=signal.direction,
            qty=qty,
            entry_price=fill.fill_price,
            opened_at=signal.timestamp,
            strategy=signal.strategy,
            stop_loss=round(fill.fill_price * (0.98 if signal.direction == "long" else 1.02), 2),
            take_profit=round(fill.fill_price * (1.03 if signal.direction == "long" else 0.97), 2),
        )
        self.alert_manager.send_alert("trade_filled", f"Trade filled for {signal.symbol}", f"{signal.strategy} {signal.direction} {qty} shares at {fill.fill_price}")

    def run(self, max_loops: int | None = None) -> None:
        self.start_background_services()
        loops = 0
        while self.running:
            now = datetime.now(tz=ZoneInfo(self.settings.timezone))
            if max_loops is not None and loops >= max_loops:
                break
            loops += 1
            if not self.market_is_open(now):
                self._log_event("info", "Market closed, skipping loop", {"timestamp": now.isoformat()})
                self.heartbeat.write("idle", {"message": "market closed"})
                time.sleep(self.settings.poll_seconds)
                continue
            regime_map: dict[str, str] = {}
            news_events = self.fetch_news(self.universe.symbols())
            incoming_bars: list[MarketBar] = []
            while True:
                try:
                    incoming_bars.append(self.bar_queue.get_nowait())
                except queue.Empty:
                    break
            if not incoming_bars:
                time.sleep(self.settings.poll_seconds)
                continue
            generated_signals: list[Signal] = []
            market_prices: dict[str, float] = {}
            for bar in incoming_bars:
                self._record_bar(bar)
                market_prices[bar.symbol] = bar.close
                self._handle_existing_positions(bar)
                regime = self.regime_detector.detect(bar.symbol)
                regime_map[bar.symbol] = regime.value
                active = self.portfolio.active_strategies(regime)
                for strategy in active:
                    signal_obj = strategy.on_bar(bar)
                    if signal_obj is not None:
                        generated_signals.append(signal_obj)
                for news_event in news_events:
                    if news_event.symbol != bar.symbol:
                        continue
                    for strategy in active:
                        signal_obj = strategy.on_news(news_event)
                        if signal_obj is not None:
                            generated_signals.append(signal_obj)
            for signal_obj in self.portfolio.aggregate(generated_signals):
                self._record_signal(signal_obj)
                latest_bar = self.bar_history[signal_obj.symbol][-1]
                self._open_position(signal_obj, latest_bar, regime_map.get(signal_obj.symbol, "UNKNOWN"))
            synced_fills = self.order_manager.sync_open_orders(market_prices)
            if synced_fills:
                self._apply_broker_fills(synced_fills, market_prices)
            self.order_manager.maybe_cancel_expired()
            self._update_dashboard_state(now, regime_map)
            if self.drawdown.state.trading_halted:
                self._log_event("error", "Circuit breaker triggered", {"drawdown_pct": self.drawdown.state.current_drawdown_pct})
                self.alert_manager.send_alert("circuit_breaker", "Trading halted", "Circuit breaker triggered")
                break
            time.sleep(self.settings.poll_seconds)
        self.feed.stop()
