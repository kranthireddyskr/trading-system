from __future__ import annotations

import argparse
from pathlib import Path

from trading_system.analytics import write_equity_curve, write_metrics_report
from trading_system.config import RiskConfig, StrategyConfig
from trading_system.data import CsvHistoricalDataProvider
from trading_system.engine import TradingEngine
from trading_system.execution import PaperExecutionEngine
from trading_system.risk import RiskManager
from trading_system.storage import FileStorageBackend, TimescaleStorageBackend, write_timescale_schema
from trading_system.strategy import MultiFactorStrategy


def build_parser():
    parser = argparse.ArgumentParser(description="Backtest and paper-trade local watchlist data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    paper_auto = subparsers.add_parser("paper-auto")
    paper_auto.add_argument("--data-dir", required=True, type=Path, help="Directory of per-symbol OHLCV CSV files")
    paper_auto.add_argument("--output-dir", type=Path, default=Path("logs"), help="Directory for runtime logs")
    paper_auto.add_argument("--poll-seconds", type=float, default=0.0)
    paper_auto.add_argument("--fast-window", type=int, default=3)
    paper_auto.add_argument("--slow-window", type=int, default=6)
    paper_auto.add_argument("--volume-window", type=int, default=5)
    paper_auto.add_argument("--volume-multiplier", type=float, default=1.1)
    paper_auto.add_argument("--min-price", type=float, default=5.0)
    paper_auto.add_argument("--max-price", type=float, default=500.0)
    paper_auto.add_argument("--min-score", type=float, default=1.15)
    paper_auto.add_argument("--breakout-window", type=int, default=8)
    paper_auto.add_argument("--mean-reversion-window", type=int, default=6)
    paper_auto.add_argument("--news-weight", type=float, default=0.35)
    paper_auto.add_argument("--breakout-weight", type=float, default=0.3)
    paper_auto.add_argument("--mean-reversion-weight", type=float, default=0.2)
    paper_auto.add_argument("--news-lookback-minutes", type=int, default=90)
    paper_auto.add_argument("--min-news-sentiment", type=float, default=-2.0)
    paper_auto.add_argument("--max-symbols-considered", type=int, default=5)
    paper_auto.add_argument("--regime-window", type=int, default=12)
    paper_auto.add_argument("--min-regime-trend-strength", type=float, default=0.0025)
    paper_auto.add_argument("--max-choppiness", type=float, default=0.75)
    paper_auto.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    paper_auto.add_argument("--max-daily-loss-pct", type=float, default=0.03)
    paper_auto.add_argument("--max-open-positions", type=int, default=3)
    paper_auto.add_argument("--max-position-notional-pct", type=float, default=0.2)
    paper_auto.add_argument("--stop-loss-pct", type=float, default=0.003)
    paper_auto.add_argument("--take-profit-pct", type=float, default=0.006)
    paper_auto.add_argument("--max-trades-per-day", type=int, default=5)
    paper_auto.add_argument("--starting-cash", type=float, default=25000.0)
    paper_auto.add_argument("--postgres-dsn", default="", help="Optional TimescaleDB/Postgres DSN for runtime storage")

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


def run_backtest(args):
    data_provider = CsvHistoricalDataProvider()
    strategy = MultiFactorStrategy(strategy_config_from_args(args))
    risk_manager = RiskManager(risk_config_from_args(args))
    storage = TimescaleStorageBackend(args.postgres_dsn) if args.postgres_dsn else FileStorageBackend(args.output_dir)
    if not args.postgres_dsn:
        write_timescale_schema(args.output_dir / "timescale_schema.sql")
    execution_engine = PaperExecutionEngine("paper_backtest")
    engine = TradingEngine(strategy, risk_manager, execution_engine, storage)
    engine.cash = args.starting_cash
    engine.buying_power = args.starting_cash
    summary = engine.run_backtest(data_provider.grouped_bars(args.data_dir), poll_seconds=args.poll_seconds)
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
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "paper-auto":
        run_backtest(args)
    else:
        raise ValueError("Unsupported command: %s" % args.command)


if __name__ == "__main__":
    main()
