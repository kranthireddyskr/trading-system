from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from trading_system.storage.models import Fill, MarketBar, Signal, SystemEvent, Trade


class FileStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        return f"FileStorage(base_dir={str(self.base_dir)!r})"

    def _daily_path(self, prefix: str, timestamp: datetime, suffix: str = "csv") -> Path:
        day = timestamp.strftime("%Y-%m-%d")
        return self.base_dir / f"{prefix}_{day}.{suffix}"

    def _append_csv(self, path: Path, headers: list[str], row: list[Any]) -> None:
        write_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(headers)
            writer.writerow(row)

    def write_bar(self, bar: MarketBar) -> None:
        self._append_csv(
            self._daily_path("bars", bar.timestamp),
            ["symbol", "timestamp", "open", "high", "low", "close", "volume", "vwap", "source"],
            [bar.symbol, bar.timestamp.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume, bar.vwap, bar.source],
        )

    def write_signal(self, signal: Signal) -> None:
        self._append_csv(
            self._daily_path("signals", signal.timestamp),
            ["symbol", "direction", "strength", "strategy", "reason", "timestamp"],
            [signal.symbol, signal.direction, signal.strength, signal.strategy, signal.reason, signal.timestamp.isoformat()],
        )

    def write_fill(self, fill: Fill) -> None:
        self._append_csv(
            self._daily_path("fills", fill.timestamp),
            ["order_id", "symbol", "side", "qty", "expected_price", "fill_price", "slippage", "commission", "timestamp"],
            [fill.order_id, fill.symbol, fill.side, fill.qty, fill.expected_price, fill.fill_price, fill.slippage, fill.commission, fill.timestamp.isoformat()],
        )

    def write_trade(self, trade: Trade) -> None:
        self._append_csv(
            self._daily_path("trades", trade.exit_time),
            ["symbol", "side", "entry_time", "exit_time", "entry_price", "exit_price", "qty", "pnl", "strategy"],
            [trade.symbol, trade.side, trade.entry_time.isoformat(), trade.exit_time.isoformat(), trade.entry_price, trade.exit_price, trade.qty, trade.pnl, trade.strategy],
        )

    def write_event(self, event: SystemEvent) -> None:
        path = self._daily_path("system_events", event.timestamp)
        self._append_csv(
            path,
            ["level", "message", "timestamp", "payload"],
            [event.level, event.message, event.timestamp.isoformat(), json.dumps(event.payload, sort_keys=True)],
        )

    def write_metrics(self, timestamp: datetime, metrics: dict[str, Any]) -> None:
        path = self._daily_path("metrics", timestamp)
        body = {"timestamp": timestamp.isoformat(), **metrics}
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def write_equity_curve(self, points: Iterable[dict[str, Any]]) -> None:
        path = self.base_dir / "equity_curve.csv"
        headers = ["timestamp", "equity", "cash", "drawdown"]
        rows = [[point["timestamp"].isoformat(), point["equity"], point["cash"], point["drawdown"]] for point in points]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)

