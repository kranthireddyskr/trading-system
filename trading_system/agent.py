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
from trading_system.data.universe import SymbolUniverse, UniverseSelector
from trading_system.execution.alpaca import AlpacaBroker
from trading_system.execution.order_manager import OrderManager
from trading_system.execution.paper import PaperBroker
from trading_system.monitoring.alerts import AlertManager
from trading_system.monitoring.dashboard import DashboardServer
from trading_system.monitoring.heartbeat import Heartbeat
from trading_system.risk.correlation import CorrelationChecker
from trading_system.risk.drawdown import DrawdownMonitor
from trading_system.risk.limits import PortfolioRiskManager, RiskLimits
from trading_system.risk.position_sizer import PositionSizer
from trading_system.storage.file_storage import FileStorage
from trading_system.storage.models import Fill, MarketBar, NewsEvent, Order, Position, Signal, SystemEvent, Trade
from trading_system.storage.timescale import TimescaleDBWriter
from trading_system.strategy.breakout import BreakoutStrategy
from trading_system.strategy.earnings_momentum import EarningsMomentumStrategy
from trading_system.strategy.gap_fade import GapFadeStrategy
from trading_system.strategy.mean_reversion import MeanReversionStrategy
from trading_system.strategy.ml_signal import MLSignalStrategy
from trading_system.strategy.momentum import MomentumStrategy
from trading_system.strategy.options_flow import OptionsFlowStrategy
from trading_system.strategy.portfolio import MultiStrategyPortfolio
from trading_system.strategy.regime import MarketRegimeDetector
from trading_system.strategy.sentiment import SentimentAnalyzer, SentimentScore


class TradingAgent:
    def __init__(
        self,
        settings: Settings,
        output_dir: Path,
        watchlist_path: Path,
        dry_run: bool = False,
        paper: bool = True,
        dashboard_port: int = 8080,
    ) -> None:
        self.settings = settings
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._build_logger()
        self.file_storage = FileStorage(self.output_dir)
        self.db_writer = TimescaleDBWriter(settings.storage_dsn, self.file_storage, settings.flush_interval_seconds)
        self.db_writer.write_schema_file(self.output_dir / "timescale_schema.sql")
        self.alert_manager = AlertManager(settings)
        self.heartbeat = Heartbeat(self.output_dir / "heartbeat.json")

        # State exposed to the dashboard
        self.state: dict[str, object] = {
            "metrics": {},
            "positions": [],
            "trades": [],
            "signals": [],
            "equity": [],
            "sentiment": {},
            "universe": [],
            "signals_history": [],
            "performance": {},
            "risk": {},
        }
        self.dashboard = DashboardServer(self._dashboard_state, port=dashboard_port)

        # Universe: static watchlist for WebSocket subscription seed;
        # UniverseSelector refreshes the traded symbol set daily.
        self.universe = SymbolUniverse(watchlist_path, settings.apca_api_key_id, settings.apca_api_secret_key)
        self.universe_selector = UniverseSelector(
            api_key=settings.apca_api_key_id,
            api_secret=settings.apca_api_secret_key,
            universe_size=settings.universe_size,
            min_price=settings.min_price,
            min_avg_volume=settings.min_avg_volume,
        )

        self.bar_queue: queue.Queue[MarketBar] = queue.Queue()
        self.feed = AlpacaWebSocketFeed(
            settings.apca_api_key_id,
            settings.apca_api_secret_key,
            self.universe.symbols(),
            self.bar_queue,
            self.logger,
        )
        self.broker = PaperBroker() if dry_run else AlpacaBroker(settings, paper=paper)
        self.order_manager = OrderManager(self.broker)
        self.position_sizer = PositionSizer()
        self.risk_limits = RiskLimits()
        self.portfolio_risk = PortfolioRiskManager(self.risk_limits)
        self.drawdown = DrawdownMonitor()
        self.correlation = CorrelationChecker()
        self.regime_detector = MarketRegimeDetector()

        self.bar_history: dict[str, list[MarketBar]] = defaultdict(list)

        # Sentiment analyser (shared bar_history reference)
        self.sentiment_analyzer = SentimentAnalyzer(
            api_key=settings.apca_api_key_id,
            api_secret=settings.apca_api_secret_key,
            bar_history=self.bar_history,
        )
        self._sentiment_cache: dict[str, SentimentScore] = {}

        self.strategies = [
            MomentumStrategy(),
            MeanReversionStrategy(),
            MLSignalStrategy(self.output_dir / "models"),
            BreakoutStrategy(),
            GapFadeStrategy(),
            EarningsMomentumStrategy(),
            OptionsFlowStrategy(),
        ]
        self.portfolio = MultiStrategyPortfolio(self.strategies)
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.signals: deque[Signal] = deque(maxlen=500)
        self.cash = 100_000.0
        self.buying_power = 100_000.0
        self.running = True
        self.dashboard_started = False
        self._register_signals()

    def __repr__(self) -> str:
        return f"TradingAgent(output_dir={str(self.output_dir)!r}, positions={len(self.positions)}, trades={len(self.trades)})"

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Market calendar helpers
    # ------------------------------------------------------------------

    def market_is_open(self, now: datetime) -> bool:
        eastern = now.astimezone(ZoneInfo(self.settings.timezone))
        if eastern.weekday() >= 5:
            return False
        open_time = eastern.replace(hour=9, minute=30, second=0, microsecond=0)
        close_time = eastern.replace(hour=16, minute=0, second=0, microsecond=0)
        return open_time <= eastern <= close_time

    def _is_near_open(self, now: datetime) -> bool:
        """True between 9:25 AM and 9:35 AM Eastern (market open window)."""
        eastern = now.astimezone(ZoneInfo(self.settings.timezone))
        t = eastern.hour * 60 + eastern.minute
        return 9 * 60 + 25 <= t <= 9 * 60 + 35

    def _is_near_close(self, now: datetime) -> bool:
        """True between 3:50 PM and 4:00 PM Eastern (market close window)."""
        eastern = now.astimezone(ZoneInfo(self.settings.timezone))
        t = eastern.hour * 60 + eastern.minute
        return 15 * 60 + 50 <= t <= 16 * 60

    # ------------------------------------------------------------------
    # Market open / close routines
    # ------------------------------------------------------------------

    def on_market_open(self, now: datetime) -> None:
        """Runs once at 9:25 AM — prepare for the trading day."""
        date_str = now.strftime("%Y-%m-%d")
        self.logger.info("=== MARKET OPEN %s ===", date_str)
        self.portfolio_risk.reset_daily_counters(date_str)

        # Refresh dynamic universe and resubscribe feed
        try:
            new_symbols = self.universe_selector.select()
            if new_symbols:
                # Always include SPY for regime/sentiment (not for trading)
                all_symbols = list(dict.fromkeys(["SPY"] + new_symbols))
                self.state["universe"] = new_symbols
                self.logger.info("Universe refreshed: %d symbols (incl. SPY for regime)", len(all_symbols))
                # Restart feed with new symbol list
                self.feed.stop()
                self.feed = AlpacaWebSocketFeed(
                    self.settings.apca_api_key_id,
                    self.settings.apca_api_secret_key,
                    all_symbols,
                    self.bar_queue,
                    self.logger,
                )
                self.feed.start()
        except Exception as exc:
            self.logger.warning("Universe refresh failed: %s", exc)

        self.reconcile_broker_state()
        self._log_event("info", "Market opened", {"date": date_str})

    def on_market_close(self, now: datetime, bars_today: int) -> None:
        """Runs once at 3:55 PM — EOD cleanup."""
        self.logger.info("=== MARKET CLOSE (bars today: %d) ===", bars_today)

        if self.settings.close_positions_eod:
            self._close_all_positions_eod()

        self._update_performance_metrics()
        self._log_event("info", "Market closed", {"bars_today": bars_today, "trades_today": len(self.trades)})

    def _close_all_positions_eod(self) -> None:
        """Market-order close every open position before EOD."""
        for symbol, position in list(self.positions.items()):
            try:
                side = "sell" if position.side == "long" else "buy"
                order = self.order_manager.submit(
                    symbol=symbol,
                    side=side,
                    qty=position.qty,
                    order_type="market",
                    strategy="eod_close",
                )
                fill = self.order_manager.fill_order(order, self.bar_history[symbol][-1].close if self.bar_history[symbol] else position.entry_price)
                if fill is None:
                    close_price = self.bar_history[symbol][-1].close if self.bar_history[symbol] else position.entry_price
                    fill = Fill(order.order_id, symbol, order.side, position.qty, close_price, close_price, 0.0, 0.0, datetime.utcnow())
                direction = 1 if position.side == "long" else -1
                pnl = round((fill.fill_price - position.entry_price) * position.qty * direction, 2)
                trade = Trade(symbol, position.side, position.opened_at, datetime.utcnow(), position.entry_price, fill.fill_price, position.qty, pnl, position.strategy)
                self.cash += round(fill.fill_price * position.qty, 2)
                self.db_writer.write_fill(fill)
                self._record_trade(trade)
                del self.positions[symbol]
                self.logger.info("EOD close: %s %s @ %.2f (pnl=%.2f)", symbol, position.side, fill.fill_price, pnl)
            except Exception as exc:
                self.logger.error("EOD close failed for %s: %s", symbol, exc)

    # ------------------------------------------------------------------
    # News fetch
    # ------------------------------------------------------------------

    def fetch_news(self, symbols: list[str]) -> list[NewsEvent]:
        headers = {
            "APCA-API-KEY-ID": self.settings.apca_api_key_id,
            "APCA-API-SECRET-KEY": self.settings.apca_api_secret_key,
        }
        try:
            response = requests.get(
                "https://data.alpaca.markets/v1beta1/news",
                headers=headers,
                params={"symbols": ",".join(symbols[:20]), "limit": 20, "sort": "desc"},
                timeout=20,
            )
            response.raise_for_status()
            news_events = []
            for item in response.json().get("news", []):
                timestamp = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                headline = item.get("headline", "").lower()
                sentiment = 1.0 if "beat" in headline else (-1.0 if "miss" in headline else 0.0)
                for sym in item.get("symbols", []):
                    news_events.append(NewsEvent(sym, item.get("headline", ""), item.get("summary", ""), timestamp, sentiment, "alpaca_news"))
            return news_events
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Background services
    # ------------------------------------------------------------------

    def start_background_services(self) -> None:
        if not self.dashboard_started:
            self.dashboard.start()
            self.dashboard_started = True
        self.feed.start()
        self.reconcile_broker_state()

    # ------------------------------------------------------------------
    # Event logging / recording
    # ------------------------------------------------------------------

    def _log_event(self, level: str, message: str, payload: dict | None = None) -> None:
        payload = payload or {}
        event = SystemEvent(level=level, message=message, timestamp=datetime.utcnow(), payload=payload)
        self.db_writer.write_event(event)
        getattr(self.logger, level.lower(), self.logger.info)(message)

    def _record_bar(self, bar: MarketBar) -> None:
        history = self.bar_history[bar.symbol]
        history.append(bar)
        self.bar_history[bar.symbol] = history[-300:]
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

    # ------------------------------------------------------------------
    # Broker state reconciliation
    # ------------------------------------------------------------------

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
                sl = round(entry_price * (1 - self.settings.stop_loss_pct if side == "long" else 1 + self.settings.stop_loss_pct), 2)
                tp = round(entry_price * (1 + self.settings.take_profit_pct if side == "long" else 1 - self.settings.take_profit_pct), 2)
                self.positions[symbol] = Position(
                    symbol=symbol, side=side, qty=qty, entry_price=entry_price,
                    opened_at=datetime.utcnow(), strategy="reconciled",
                    stop_loss=sl, take_profit=tp,
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

    # ------------------------------------------------------------------
    # Mark-to-market / dashboard helpers
    # ------------------------------------------------------------------

    def _mark_to_market_equity(self) -> float:
        equity = self.cash
        for symbol, position in self.positions.items():
            if self.bar_history[symbol]:
                price = self.bar_history[symbol][-1].close
                direction = 1 if position.side == "long" else -1
                equity += round(position.qty * (position.entry_price + ((price - position.entry_price) * direction)), 2)
        return round(equity, 2)

    def _update_performance_metrics(self) -> None:
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        losses = [t.pnl for t in self.trades if t.pnl <= 0]
        total_trades = len(self.trades)
        win_rate = round(len(wins) / total_trades * 100, 2) if total_trades else 0.0
        avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
        avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
        profit_factor = round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else 0.0
        total_pnl = round(sum(t.pnl for t in self.trades), 2)
        self.state["performance"] = {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "sharpe": None,
            "max_drawdown_pct": round(self.drawdown.state.max_drawdown_pct * 100, 2) if hasattr(self.drawdown.state, "max_drawdown_pct") else None,
        }

    def _update_dashboard_state(self, now: datetime, regime_map: dict[str, str]) -> None:
        equity = self._mark_to_market_equity()
        drawdown_state = self.drawdown.update_equity(now, equity)
        wins = [t for t in self.trades if t.pnl > 0]
        metrics = {
            "equity": equity,
            "cash": round(self.cash, 2),
            "positions": len(self.positions),
            "win_rate": round(len(wins) / len(self.trades) * 100, 2) if self.trades else 0.0,
            "daily_pnl": round(equity - max(self.drawdown.state.daily_start_equity, 100_000.0), 2),
            "drawdown_pct": round(drawdown_state.current_drawdown_pct * 100, 2),
            "circuit_breaker": drawdown_state.trading_halted,
            "regime": regime_map,
        }
        self.state["metrics"] = metrics

        # Enrich positions with last price and unrealised P&L
        pos_list = []
        for sym, pos in self.positions.items():
            last_price = self.bar_history[sym][-1].close if self.bar_history[sym] else pos.entry_price
            direction = 1 if pos.side == "long" else -1
            unrealised = round((last_price - pos.entry_price) * pos.qty * direction, 2)
            d = dict(pos.__dict__)
            d["last_price"] = last_price
            d["unrealised_pnl"] = unrealised
            pos_list.append(d)
        self.state["positions"] = pos_list

        self.state["trades"] = [t.__dict__ for t in self.trades[-50:]]
        self.state["signals"] = [s.__dict__ for s in list(self.signals)[-50:]]
        self.state["signals_history"] = [s.__dict__ for s in list(self.signals)]

        # Sentiment snapshot
        self.state["sentiment"] = {sym: vars(score) for sym, score in self._sentiment_cache.items()}

        # Risk / sector exposure
        sector_exposures = self.portfolio_risk.sector_exposures(self.positions, equity)
        self.state["risk"] = {
            "sector_exposures": sector_exposures,
            "max_sector_pct": self.risk_limits.max_sector_pct,
            "daily_trades": self.portfolio_risk._daily_trade_count,
            "max_daily_trades": self.risk_limits.max_trades_per_day,
        }

        equity_points = self.state.setdefault("equity", [])
        equity_points.append({"timestamp": now.isoformat(), "equity": equity, "cash": round(self.cash, 2), "drawdown": round(drawdown_state.current_drawdown_pct * 100, 2)})
        self.state["equity"] = equity_points[-500:]

        self.heartbeat.write("ok", metrics)
        self.db_writer.write_metrics(now, metrics)
        self._update_performance_metrics()

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

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
        try:
            order = self.order_manager.submit(
                symbol=bar.symbol,
                side="sell" if position.side == "long" else "buy",
                qty=position.qty,
                order_type="market",
                strategy=position.strategy,
            )
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
        except Exception as exc:
            self.logger.error("Failed to close position for %s: %s", bar.symbol, exc)

    def _apply_broker_fills(self, fills: list[Fill], market_prices: dict[str, float]) -> None:
        for fill in fills:
            self.db_writer.write_fill(fill)
            side = fill.side.lower()
            existing = self.positions.get(fill.symbol)
            if existing is None and side in {"buy", "long"}:
                sl = round(fill.fill_price * (1 - self.settings.stop_loss_pct), 2)
                tp = round(fill.fill_price * (1 + self.settings.take_profit_pct), 2)
                self.cash -= round(fill.fill_price * fill.qty, 2)
                self.positions[fill.symbol] = Position(
                    symbol=fill.symbol, side="long", qty=fill.qty,
                    entry_price=fill.fill_price, opened_at=fill.timestamp,
                    strategy="broker_sync", stop_loss=sl, take_profit=tp,
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

    # ------------------------------------------------------------------
    # Position opening — with sentiment gate + portfolio risk check
    # ------------------------------------------------------------------

    def _open_position(self, signal: Signal, bar: MarketBar, regime_label: str) -> None:
        # ── basic guards ──────────────────────────────────────────────
        if signal.symbol in self.positions:
            self.logger.info("Signal rejected: already have open position in %s", signal.symbol)
            return
        if bar.close < self.risk_limits.min_price or bar.volume < self.risk_limits.min_volume:
            self.logger.info("Signal rejected: price/volume filter for %s (close=%.2f vol=%d min_vol=%d)", signal.symbol, bar.close, bar.volume, self.risk_limits.min_volume)
            return
        if not self.correlation.is_allowed(signal.symbol, list(self.positions.values()), self.bar_history):
            self.logger.info("Signal rejected: correlation check failed for %s", signal.symbol)
            return

        # ── sentiment gate ────────────────────────────────────────────
        try:
            sentiment = self.sentiment_analyzer.get_composite_sentiment(signal.symbol)
            self._sentiment_cache[signal.symbol] = sentiment
        except Exception as exc:
            self.logger.debug("Sentiment fetch failed for %s: %s — skipping gate", signal.symbol, exc)
            sentiment = None

        if sentiment is not None:
            gate = self.settings.sentiment_gate_threshold
            if signal.direction == "long" and sentiment.score < -gate:
                self.logger.info("Signal rejected: bearish sentiment (%.3f < -%.2f) for %s long", sentiment.score, gate, signal.symbol)
                return
            if signal.direction == "short" and sentiment.score > gate:
                self.logger.info("Signal rejected: bullish sentiment (%.3f > +%.2f) for %s short", sentiment.score, gate, signal.symbol)
                return

        # ── position sizing ───────────────────────────────────────────
        win_rate = len([t for t in self.trades if t.pnl > 0]) / len(self.trades) if self.trades else 0.5
        avg_win = sum(t.pnl for t in self.trades if t.pnl > 0) / len([t for t in self.trades if t.pnl > 0]) if any(t.pnl > 0 for t in self.trades) else 100.0
        avg_loss = sum(t.pnl for t in self.trades if t.pnl <= 0) / len([t for t in self.trades if t.pnl <= 0]) if any(t.pnl <= 0 for t in self.trades) else -50.0
        atr_like = max(abs((bar.high - bar.low) / max(bar.close, 0.01)), 0.01)
        multiplier = self.drawdown.size_multiplier()
        if regime_label == "HIGH_VOLATILITY":
            multiplier *= 0.5
        # Scale by sentiment magnitude: |score| < 0.3 → 50%, < 0.6 → 75%, else 100%
        if sentiment is not None:
            abs_score = abs(sentiment.score)
            if abs_score < 0.3:
                multiplier *= 0.5
            elif abs_score < 0.6:
                multiplier *= 0.75

        qty = self.position_sizer.size(self.cash, bar.close, atr_like, win_rate, avg_win, avg_loss, multiplier)
        if qty <= 0:
            self.logger.info("Signal rejected: position sizer returned qty=0 for %s", signal.symbol)
            return

        # ── portfolio risk manager check ──────────────────────────────
        notional = qty * bar.close
        equity = self._mark_to_market_equity()
        allowed, reason = self.portfolio_risk.is_position_allowed(signal.symbol, notional, self.positions, equity)
        if not allowed:
            self.logger.info("Signal rejected by PortfolioRiskManager for %s: %s", signal.symbol, reason)
            return

        # ── compute bracket prices from settings ──────────────────────
        sl_pct = self.settings.stop_loss_pct
        tp_pct = self.settings.take_profit_pct
        if signal.direction == "long":
            stop_loss_price = round(bar.close * (1 - sl_pct), 2)
            take_profit_price = round(bar.close * (1 + tp_pct), 2)
        else:
            stop_loss_price = round(bar.close * (1 + sl_pct), 2)
            take_profit_price = round(bar.close * (1 - tp_pct), 2)

        side = "buy" if signal.direction == "long" else "sell"
        self.logger.info(
            "Order submitted: %s %s %s shares @ market (sl=%.2f tp=%.2f sent=%.3f)",
            signal.symbol, side.upper(), qty, stop_loss_price, take_profit_price,
            sentiment.score if sentiment else 0.0,
        )

        order_kwargs: dict = dict(
            symbol=signal.symbol,
            side=side,
            qty=qty,
            order_type="market",
            strategy=signal.strategy,
        )
        if self.settings.bracket_orders:
            order_kwargs["stop_loss_price"] = stop_loss_price
            order_kwargs["take_profit_price"] = take_profit_price

        order = self.order_manager.submit(**order_kwargs)
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
            stop_loss=stop_loss_price,
            take_profit=take_profit_price,
        )
        self.portfolio_risk.record_trade()
        self.alert_manager.send_alert(
            "trade_filled",
            f"Trade filled for {signal.symbol}",
            f"{signal.strategy} {signal.direction} {qty} shares at {fill.fill_price}",
        )

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self, max_loops: int | None = None) -> None:
        self.start_background_services()
        loops = 0
        bars_processed = 0
        _market_was_open = False
        _open_routine_done = False
        _close_routine_done = False

        while self.running:
            now = datetime.now(tz=ZoneInfo(self.settings.timezone))
            if max_loops is not None and loops >= max_loops:
                break
            loops += 1

            market_open = self.market_is_open(now)

            # Market open transition
            if market_open and not _market_was_open:
                _open_routine_done = False
                _close_routine_done = False
                bars_processed = 0

            # Near-open routine (9:25–9:35 AM)
            if market_open and not _open_routine_done and self._is_near_open(now):
                self.on_market_open(now)
                _open_routine_done = True

            # Near-close routine (3:50–4:00 PM)
            if market_open and not _close_routine_done and self._is_near_close(now):
                self.on_market_close(now, bars_processed)
                _close_routine_done = True

            if not market_open and _market_was_open:
                self.logger.info("MARKET CLOSE - stopping bar processing (bars today: %d)", bars_processed)

            _market_was_open = market_open

            if not market_open:
                self._log_event("info", "Market closed, skipping loop", {"timestamp": now.isoformat()})
                self.heartbeat.write("idle", {"message": "market closed"})
                time.sleep(self.settings.poll_seconds)
                continue

            self.logger.info("Checking queue, size: %d", self.bar_queue.qsize())

            regime_map: dict[str, str] = {}
            news_events = self.fetch_news(self.universe.symbols()[:20])

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
                bars_processed += 1
                self.logger.info("Processing bar: %s @ %.4f volume=%s", bar.symbol, bar.close, bar.volume)
                if bars_processed % 10 == 0:
                    self.logger.info("Processed %d bars today", bars_processed)

                self._record_bar(bar)
                market_prices[bar.symbol] = bar.close
                self._handle_existing_positions(bar)

                regime = self.regime_detector.detect(bar.symbol)
                regime_map[bar.symbol] = regime.value
                active = self.portfolio.active_strategies(regime)

                for strategy in active:
                    signal_obj = strategy.on_bar(bar)
                    if signal_obj is not None:
                        self.logger.info("Signal: %s %s strength=%.2f from %s", signal_obj.symbol, signal_obj.direction, signal_obj.strength, signal_obj.strategy)
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
                if signal_obj.direction == "close":
                    self.logger.info("Skipping close signal for %s (exits managed by stop/tp)", signal_obj.symbol)
                    continue
                if not self.bar_history[signal_obj.symbol]:
                    continue
                latest_bar = self.bar_history[signal_obj.symbol][-1]
                try:
                    self._open_position(signal_obj, latest_bar, regime_map.get(signal_obj.symbol, "UNKNOWN"))
                except Exception as exc:
                    self.logger.error("Order failed for %s, continuing: %s", signal_obj.symbol, exc)

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
