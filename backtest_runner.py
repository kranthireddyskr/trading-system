from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from trading_system.backtest.engine import BacktestEngine
from trading_system.backtest.report import ReportGenerator
from trading_system.backtest.validation import summarize_metrics, write_validation_summary
from trading_system.config.settings import Settings, ensure_watchlist
from trading_system.data.historical import HistoricalDataLoader
from trading_system.strategy.mean_reversion import MeanReversionStrategy
from trading_system.strategy.ml_signal import MLSignalStrategy
from trading_system.strategy.momentum import MomentumStrategy
from trading_system.strategy.portfolio import MultiStrategyPortfolio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest runner")
    parser.add_argument("--data-dir", default="backtest_cache")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--watchlist", default="trading_system/config/watchlist.txt")
    parser.add_argument("--strategy", default="all", choices=["momentum", "mean_reversion", "ml", "all"])
    parser.add_argument("--capital", type=float, default=100000)
    parser.add_argument("--output-dir", default="backtest_results")
    parser.add_argument("--validation-windows", type=int, default=1)
    return parser


def load_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    watchlist_path = Path(args.watchlist)
    ensure_watchlist(watchlist_path)
    return [line.strip().upper().replace("\ufeff", "") for line in watchlist_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def selected_strategies(strategy_name: str, output_dir: Path) -> list:
    mapping = {
        "momentum": [MomentumStrategy()],
        "mean_reversion": [MeanReversionStrategy()],
        "ml": [MLSignalStrategy(output_dir / "models")],
        "all": [MomentumStrategy(), MeanReversionStrategy(), MLSignalStrategy(output_dir / "models")],
    }
    return mapping[strategy_name]


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings()
    symbols = load_symbols(args)
    data_loader = HistoricalDataLoader(settings.apca_api_key_id, settings.apca_api_secret_key, Path(args.data_dir))
    data_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        frame = data_loader.load(symbol, args.start_date, args.end_date, timeframe="1Min")
        if not frame.empty:
            data_by_symbol[symbol] = frame
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    strategies = selected_strategies(args.strategy, output_dir)
    portfolio = MultiStrategyPortfolio(strategies)
    engine = BacktestEngine(starting_capital=args.capital)
    result = engine.run(data_by_symbol, strategies, portfolio)
    report = ReportGenerator()
    report.generate(output_dir / "backtest_report.html", result.metrics, result.equity_curve, result.trades)
    validation_metrics = [result.metrics]
    validation_windows: list[dict] = [{
        "window": 1,
        "total_return_pct": result.metrics.total_return_pct,
        "sharpe_ratio": result.metrics.sharpe_ratio,
        "sortino_ratio": result.metrics.sortino_ratio,
        "calmar_ratio": result.metrics.calmar_ratio,
        "trades": result.metrics.number_of_trades,
    }]
    if args.validation_windows > 1:
        symbols_frames = {}
        for symbol, frame in data_by_symbol.items():
            symbols_frames[symbol] = frame.sort_index()
        for window_index in range(1, args.validation_windows):
            sliced: dict[str, pd.DataFrame] = {}
            for symbol, frame in symbols_frames.items():
                if len(frame) < 50:
                    continue
                start_offset = int((len(frame) / args.validation_windows) * window_index)
                sliced_frame = frame.iloc[start_offset:]
                if not sliced_frame.empty:
                    sliced[symbol] = sliced_frame
            if not sliced:
                continue
            window_result = BacktestEngine(starting_capital=args.capital).run(sliced, selected_strategies(args.strategy, output_dir / f"window_{window_index}"), MultiStrategyPortfolio(selected_strategies(args.strategy, output_dir / f"window_{window_index}")))
            validation_metrics.append(window_result.metrics)
            validation_windows.append({
                "window": window_index + 1,
                "total_return_pct": window_result.metrics.total_return_pct,
                "sharpe_ratio": window_result.metrics.sharpe_ratio,
                "sortino_ratio": window_result.metrics.sortino_ratio,
                "calmar_ratio": window_result.metrics.calmar_ratio,
                "trades": window_result.metrics.number_of_trades,
            })
    validation_summary = summarize_metrics(validation_metrics)
    write_validation_summary(output_dir / "validation_summary.json", validation_summary, validation_windows)
    print("Backtest Summary")
    print(f"Total Return %   : {result.metrics.total_return_pct:.2f}")
    print(f"Annualized Return: {result.metrics.annualized_return_pct:.2f}")
    print(f"Sharpe Ratio     : {result.metrics.sharpe_ratio:.2f}")
    print(f"Sortino Ratio    : {result.metrics.sortino_ratio:.2f}")
    print(f"Calmar Ratio     : {result.metrics.calmar_ratio:.2f}")
    print(f"Max Drawdown %   : {result.metrics.max_drawdown_pct:.2f}")
    print(f"Win Rate %       : {result.metrics.win_rate_pct:.2f}")
    print(f"Profit Factor    : {result.metrics.profit_factor:.2f}")
    print(f"Trades           : {result.metrics.number_of_trades}")
    print("Validation Summary")
    print(f"Windows Run      : {validation_summary.windows_run}")
    print(f"Avg Sharpe       : {validation_summary.average_sharpe:.2f}")
    print(f"Avg Sortino      : {validation_summary.average_sortino:.2f}")
    print(f"Avg Calmar       : {validation_summary.average_calmar:.2f}")
    print(f"Avg Win Rate %   : {validation_summary.average_win_rate:.2f}")
    print(f"Avg Max DD %     : {validation_summary.average_max_drawdown:.2f}")


if __name__ == "__main__":
    main()
