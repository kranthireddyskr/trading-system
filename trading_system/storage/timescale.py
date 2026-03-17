from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json

from trading_system.storage.file_storage import FileStorage
from trading_system.storage.models import Fill, MarketBar, Signal, SystemEvent, Trade


TIMESCALE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS market_bars (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL,
    vwap DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL
);
SELECT create_hypertable('market_bars', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS signals (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    direction TEXT NOT NULL,
    strength DOUBLE PRECISION NOT NULL,
    strategy TEXT NOT NULL,
    reason TEXT NOT NULL
);
SELECT create_hypertable('signals', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS fills (
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    side TEXT NOT NULL,
    qty DOUBLE PRECISION NOT NULL,
    expected_price DOUBLE PRECISION NOT NULL,
    fill_price DOUBLE PRECISION NOT NULL,
    slippage DOUBLE PRECISION NOT NULL,
    commission DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('fills', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS trades (
    symbol TEXT NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ NOT NULL,
    side TEXT NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION NOT NULL,
    qty DOUBLE PRECISION NOT NULL,
    pnl DOUBLE PRECISION NOT NULL,
    strategy TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_events (
    ts TIMESTAMPTZ NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    payload JSONB NOT NULL
);
SELECT create_hypertable('system_events', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS performance_metrics (
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
SELECT create_hypertable('performance_metrics', 'ts', if_not_exists => TRUE);
""".strip()


class TimescaleDBWriter:
    def __init__(self, dsn: str, fallback_storage: FileStorage, flush_interval: int = 5) -> None:
        self.dsn = dsn
        self.fallback_storage = fallback_storage
        self.flush_interval = flush_interval
        self.connection = None
        self.enabled = False
        if dsn:
            try:
                self.connection = psycopg2.connect(dsn)
                self.connection.autocommit = True
                self.enabled = True
                self.ensure_schema()
            except Exception:
                self.enabled = False

    def __repr__(self) -> str:
        return f"TimescaleDBWriter(enabled={self.enabled}, flush_interval={self.flush_interval})"

    def ensure_schema(self) -> None:
        if not self.enabled or self.connection is None:
            return
        with self.connection.cursor() as cursor:
            cursor.execute(TIMESCALE_SCHEMA_SQL)

    def write_schema_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TIMESCALE_SCHEMA_SQL + "\n", encoding="utf-8")

    def _execute(self, query: str, params: tuple[Any, ...], fallback_callable: callable) -> None:
        if not self.enabled or self.connection is None:
            fallback_callable()
            return
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
        except Exception:
            fallback_callable()

    def write_bar(self, bar: MarketBar) -> None:
        self._execute(
            "INSERT INTO market_bars(symbol, ts, open, high, low, close, volume, vwap, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (bar.symbol, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.vwap, bar.source),
            lambda: self.fallback_storage.write_bar(bar),
        )

    def write_signal(self, signal: Signal) -> None:
        self._execute(
            "INSERT INTO signals(symbol, ts, direction, strength, strategy, reason) VALUES (%s,%s,%s,%s,%s,%s)",
            (signal.symbol, signal.timestamp, signal.direction, signal.strength, signal.strategy, signal.reason),
            lambda: self.fallback_storage.write_signal(signal),
        )

    def write_fill(self, fill: Fill) -> None:
        self._execute(
            "INSERT INTO fills(order_id, symbol, ts, side, qty, expected_price, fill_price, slippage, commission) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (fill.order_id, fill.symbol, fill.timestamp, fill.side, fill.qty, fill.expected_price, fill.fill_price, fill.slippage, fill.commission),
            lambda: self.fallback_storage.write_fill(fill),
        )

    def write_trade(self, trade: Trade) -> None:
        self._execute(
            "INSERT INTO trades(symbol, entry_time, exit_time, side, entry_price, exit_price, qty, pnl, strategy) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (trade.symbol, trade.entry_time, trade.exit_time, trade.side, trade.entry_price, trade.exit_price, trade.qty, trade.pnl, trade.strategy),
            lambda: self.fallback_storage.write_trade(trade),
        )

    def write_event(self, event: SystemEvent) -> None:
        self._execute(
            "INSERT INTO system_events(ts, level, message, payload) VALUES (%s,%s,%s,%s)",
            (event.timestamp, event.level, event.message, Json(event.payload)),
            lambda: self.fallback_storage.write_event(event),
        )

    def write_metrics(self, timestamp: datetime, metrics: dict[str, Any]) -> None:
        self._execute(
            "INSERT INTO performance_metrics(ts, payload) VALUES (%s,%s)",
            (timestamp, Json(metrics)),
            lambda: self.fallback_storage.write_metrics(timestamp, metrics),
        )
