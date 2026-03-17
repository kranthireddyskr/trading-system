from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from trading_system.backtest.metrics import PerformanceMetrics


@dataclass
class ValidationSummary:
    windows_run: int
    average_sharpe: float
    average_sortino: float
    average_calmar: float
    average_win_rate: float
    average_max_drawdown: float
    total_trades: int

    def __repr__(self) -> str:
        return f"ValidationSummary(windows_run={self.windows_run}, average_sharpe={self.average_sharpe:.2f}, total_trades={self.total_trades})"


def summarize_metrics(metrics_list: list[PerformanceMetrics]) -> ValidationSummary:
    if not metrics_list:
        return ValidationSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    count = len(metrics_list)
    return ValidationSummary(
        windows_run=count,
        average_sharpe=round(sum(item.sharpe_ratio for item in metrics_list) / count, 2),
        average_sortino=round(sum(item.sortino_ratio for item in metrics_list) / count, 2),
        average_calmar=round(sum(item.calmar_ratio for item in metrics_list) / count, 2),
        average_win_rate=round(sum(item.win_rate_pct for item in metrics_list) / count, 2),
        average_max_drawdown=round(sum(item.max_drawdown_pct for item in metrics_list) / count, 2),
        total_trades=sum(item.number_of_trades for item in metrics_list),
    )


def write_validation_summary(path: Path, summary: ValidationSummary, windows: list[dict]) -> None:
    payload = {
        "summary": summary.__dict__,
        "windows": windows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

