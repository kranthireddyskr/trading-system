from __future__ import annotations

import csv
import math
from pathlib import Path


def mean(values):
    return sum(values) / float(len(values)) if values else 0.0


def stddev(values):
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / float(len(values) - 1)
    return math.sqrt(max(variance, 0.0))


def compute_performance_metrics(equity_curve, closed_trades):
    returns = []
    previous_equity = None
    for point in equity_curve:
        equity = point["equity"]
        if previous_equity and previous_equity > 0:
            returns.append((equity / previous_equity) - 1.0)
        previous_equity = equity

    downside_returns = [value for value in returns if value < 0]
    avg_return = mean(returns)
    sharpe = 0.0
    volatility = stddev(returns)
    if volatility > 0:
        sharpe = (avg_return / volatility) * math.sqrt(252.0)

    sortino = 0.0
    downside_volatility = stddev(downside_returns)
    if downside_volatility > 0:
        sortino = (avg_return / downside_volatility) * math.sqrt(252.0)

    peak = None
    max_drawdown = 0.0
    for point in equity_curve:
        equity = point["equity"]
        if peak is None or equity > peak:
            peak = equity
        if peak and peak > 0:
            drawdown = (peak - equity) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown

    wins = [trade.pnl for trade in closed_trades if trade.pnl > 0]
    losses = [trade.pnl for trade in closed_trades if trade.pnl <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
    win_rate = (float(len(wins)) / len(closed_trades)) if closed_trades else 0.0

    return {
        "closed_trades": len(closed_trades),
        "win_rate": win_rate,
        "average_win": mean(wins),
        "average_loss": mean(losses),
        "profit_factor": profit_factor,
        "net_pnl": sum(trade.pnl for trade in closed_trades),
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "ending_equity": equity_curve[-1]["equity"] if equity_curve else 0.0,
    }


def write_equity_curve(path, equity_curve):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "equity", "cash", "gross_exposure"])
        for point in equity_curve:
            writer.writerow([
                point["timestamp"].isoformat(),
                "%.2f" % point["equity"],
                "%.2f" % point["cash"],
                "%.2f" % point["gross_exposure"],
            ])


def write_metrics_report(path, metrics):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "closed_trades=%s" % metrics["closed_trades"],
        "win_rate=%.4f" % metrics["win_rate"],
        "average_win=%.4f" % metrics["average_win"],
        "average_loss=%.4f" % metrics["average_loss"],
        "profit_factor=%.4f" % metrics["profit_factor"],
        "net_pnl=%.4f" % metrics["net_pnl"],
        "max_drawdown=%.4f" % metrics["max_drawdown"],
        "sharpe_ratio=%.4f" % metrics["sharpe_ratio"],
        "sortino_ratio=%.4f" % metrics["sortino_ratio"],
        "ending_equity=%.4f" % metrics["ending_equity"],
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

