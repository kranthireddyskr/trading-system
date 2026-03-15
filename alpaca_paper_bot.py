from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from trading_system.analytics import write_equity_curve, write_metrics_report
from trading_system.config import RiskConfig, StrategyConfig
from trading_system.data import AlpacaMarketDataClient
from trading_system.engine import TradingEngine
from trading_system.execution import AlpacaBrokerClient, AlpacaExecutionEngine, PaperExecutionEngine
from trading_system.monitoring import Monitor
from trading_system.risk import RiskManager
from trading_system.schedule import market_session_allows
from trading_system.secrets import resolve_secret
from trading_system.storage import FileStorageBackend, TimescaleStorageBackend, write_timescale_schema
from trading_system.strategy import MultiFactorStrategy
from trading_system.utils import parse_timestamp


def load_symbols(path):
    symbols = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            symbol = line.strip().upper()
            if symbol and not symbol.startswith("#"):
                symbols.append(symbol)
    if not symbols:
        raise ValueError("No symbols found in watchlist file")
    return symbols


def build_parser():
    parser = argparse.ArgumentParser(description="Real-time paper trader using Alpaca data and order routing")
    parser.add_argument("--watchlist", type=Path, required=True, help="Path to a newline-delimited watchlist file")
    parser.add_argument("--output-dir", type=Path, default=Path("live_logs"), help="Directory for logs")
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--news-poll-seconds", type=int, default=60)
    parser.add_argument("--fast-window", type=int, default=3)
    parser.add_argument("--slow-window", type=int, default=6)
    parser.add_argument("--volume-window", type=int, default=5)
    parser.add_argument("--volume-multiplier", type=float, default=1.1)
    parser.add_argument("--breakout-window", type=int, default=8)
    parser.add_argument("--mean-reversion-window", type=int, default=6)
    parser.add_argument("--min-score", type=float, default=1.15)
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--max-price", type=float, default=500.0)
    parser.add_argument("--stop-loss-pct", type=float, default=0.003)
    parser.add_argument("--take-profit-pct", type=float, default=0.006)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--max-daily-loss-pct", type=float, default=0.03)
    parser.add_argument("--max-open-positions", type=int, default=3)
    parser.add_argument("--max-position-notional-pct", type=float, default=0.2)
    parser.add_argument("--max-trades-per-day", type=int, default=5)
    parser.add_argument("--max-symbols-considered", type=int, default=5)
    parser.add_argument("--news-lookback-minutes", type=int, default=90)
    parser.add_argument("--news-weight", type=float, default=0.35)
    parser.add_argument("--breakout-weight", type=float, default=0.3)
    parser.add_argument("--mean-reversion-weight", type=float, default=0.2)
    parser.add_argument("--min-news-sentiment", type=float, default=-2.0)
    parser.add_argument("--regime-window", type=int, default=12)
    parser.add_argument("--min-regime-trend-strength", type=float, default=0.0025)
    parser.add_argument("--max-choppiness", type=float, default=0.75)
    parser.add_argument("--data-feed", default="iex", choices=["iex", "sip", "delayed_sip"], help="Alpaca stock data feed")
    parser.add_argument("--mode", default="rest", choices=["rest", "websocket"], help="Market data mode")
    parser.add_argument("--session", default="regular", choices=["regular", "extended"], help="Allowed trading session window")
    parser.add_argument("--exit-after-close", action="store_true", help="Stop the process after the allowed session closes")
    parser.add_argument("--alert-webhook-url", default=os.getenv("TRADING_ALERT_WEBHOOK_URL", ""))
    parser.add_argument("--postgres-dsn", default=os.getenv("TIMESCALE_POSTGRES_DSN", ""))
    parser.add_argument("--dry-run", action="store_true", help="Use simulated fills instead of Alpaca paper orders")
    parser.add_argument("--max-loops", type=int, default=None, help="Optional loop limit for testing")
    return parser


def strategy_config_from_args(args):
    return StrategyConfig(
        fast_window=args.fast_window,
        slow_window=args.slow_window,
        volume_window=args.volume_window,
        volume_multiplier=args.volume_multiplier,
        breakout_window=args.breakout_window,
        mean_reversion_window=args.mean_reversion_window,
        min_price=args.min_price,
        max_price=args.max_price,
        min_score=args.min_score,
        news_weight=args.news_weight,
        breakout_weight=args.breakout_weight,
        mean_reversion_weight=args.mean_reversion_weight,
        news_lookback_minutes=args.news_lookback_minutes,
        min_news_sentiment=args.min_news_sentiment,
        max_symbols_considered=args.max_symbols_considered,
        regime_window=args.regime_window,
        min_regime_trend_strength=args.min_regime_trend_strength,
        max_choppiness=args.max_choppiness,
    )


def risk_config_from_args(args):
    return RiskConfig(
        risk_per_trade_pct=args.risk_per_trade_pct,
        max_daily_loss_pct=args.max_daily_loss_pct,
        max_open_positions=args.max_open_positions,
        max_position_notional_pct=args.max_position_notional_pct,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        max_trades_per_day=args.max_trades_per_day,
    )


def resolve_credentials():
    api_key = resolve_secret("APCA_API_KEY_ID")
    api_secret = resolve_secret("APCA_API_SECRET_KEY")
    if not api_key or not api_secret:
        raise EnvironmentError("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY, or provide them through TRADING_SECRET_FILE or AWS Secrets Manager.")
    return api_key, api_secret


def build_storage(args):
    if args.postgres_dsn:
        return TimescaleStorageBackend(args.postgres_dsn)
    write_timescale_schema(args.output_dir / "timescale_schema.sql")
    return FileStorageBackend(args.output_dir)


def run_live(args):
    api_key, api_secret = resolve_credentials()
    symbols = load_symbols(args.watchlist)
    strategy = MultiFactorStrategy(strategy_config_from_args(args))
    risk_manager = RiskManager(risk_config_from_args(args))
    storage = build_storage(args)
    monitor = Monitor(
        heartbeat_path=args.output_dir / "heartbeat.json",
        dashboard_path=args.output_dir / "dashboard.json",
        alerts_path=args.output_dir / "alerts.log",
        alert_webhook_url=args.alert_webhook_url,
    )
    broker_client = AlpacaBrokerClient(api_key, api_secret)
    execution_engine = PaperExecutionEngine("alpaca_paper_sim") if args.dry_run else AlpacaExecutionEngine(broker_client)
    engine = TradingEngine(strategy, risk_manager, execution_engine, storage, broker_client=broker_client, monitor=monitor)

    account = broker_client.get_account()
    starting_equity = float(account.get("portfolio_value", account.get("equity", 0.0)))
    engine.cash = float(account.get("cash", starting_equity))
    engine.buying_power = float(account.get("buying_power", engine.cash))
    engine.daily_start_equity = starting_equity

    data_client = AlpacaMarketDataClient(api_key, api_secret, data_feed=args.data_feed)
    if args.mode == "websocket":
        storage.store_system_event("mode_notice", {
            "mode": "websocket",
            "status": "falling_back_to_rest_polling",
            "reason": "websocket runtime loop is scaffolded but not fully wired in this environment",
        })

    loop_count = 0
    last_news_poll_at = None
    while True:
        if args.max_loops is not None and loop_count >= args.max_loops:
            break
        loop_count += 1

        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                clock_future = executor.submit(broker_client.get_clock)
                snapshots_future = executor.submit(data_client.get_snapshots, symbols)
                news_due = last_news_poll_at is None
                if not news_due:
                    pass

                clock = clock_future.result()
                now = parse_timestamp(clock["timestamp"])
                if not market_session_allows(now, args.session):
                    storage.store_system_event("session_block", {"session": args.session, "timestamp": now.isoformat()})
                    monitor.heartbeat("idle", {"session": args.session, "reason": "outside_allowed_session"})
                    if args.exit_after_close:
                        break
                    time.sleep(args.poll_seconds)
                    continue
                if not clock.get("is_open") and args.session == "regular":
                    storage.store_system_event("market_closed", {"next_open": clock.get("next_open", "unknown")})
                    if args.exit_after_close:
                        break
                    time.sleep(args.poll_seconds)
                    continue

                snapshots = snapshots_future.result()
                if not snapshots:
                    storage.store_system_event("data_warning", {"reason": "no_snapshots_returned"})
                for bar in snapshots:
                    engine.ingest_bar(bar)

                if last_news_poll_at is None or (now - last_news_poll_at).total_seconds() >= args.news_poll_seconds:
                    news_future = executor.submit(data_client.get_news, symbols, now, args.news_lookback_minutes, 50)
                    news_events = news_future.result()
                    for event in news_events:
                        engine.ingest_news(event)
                    last_news_poll_at = now

            engine.evaluate_exits(now)
            engine.evaluate_entries(now)
            summary = engine.record_equity(now)
            storage.store_system_event("loop_complete", {
                "equity": summary.equity,
                "cash": summary.cash,
                "open_positions": len(engine.positions),
            })
            time.sleep(args.poll_seconds)
        except Exception as exc:
            risk_manager.halt("runtime_failure")
            storage.store_system_event("circuit_breaker", {"error": str(exc)})
            monitor.alert("circuit_breaker", {"error": str(exc)})
            monitor.heartbeat("halted", {"error": str(exc)})
            raise

    summary = engine.summary()
    storage.write_metrics(summary)
    write_equity_curve(args.output_dir / "equity_curve.csv", engine.equity_curve)
    write_metrics_report(args.output_dir / "metrics.txt", summary)
    print("\nSummary")
    print("Closed trades : %s" % summary["closed_trades"])
    print("Win rate      : %.2f%%" % (summary["win_rate"] * 100.0))
    print("Average win   : %.2f" % summary["average_win"])
    print("Average loss  : %.2f" % summary["average_loss"])
    print("Profit factor : %.2f" % summary["profit_factor"])
    print("Net PnL       : %.2f" % summary["net_pnl"])
    print("Max drawdown  : %.2f%%" % (summary["max_drawdown"] * 100.0))
    print("Sharpe ratio  : %.2f" % summary["sharpe_ratio"])
    print("Sortino ratio : %.2f" % summary["sortino_ratio"])
    print("Cash          : %.2f" % summary["cash"])


def main():
    args = build_parser().parse_args()
    run_live(args)


if __name__ == "__main__":
    main()
