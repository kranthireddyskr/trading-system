from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from trading_system.models import ClosedTrade, FillEvent, MarketBar, NewsEvent, Signal


class StorageBackend(object):
    def store_bar(self, bar):
        raise NotImplementedError

    def store_news(self, news):
        raise NotImplementedError

    def store_signal(self, signal):
        raise NotImplementedError

    def store_fill(self, fill):
        raise NotImplementedError

    def store_trade(self, trade):
        raise NotImplementedError

    def store_system_event(self, event_type, payload):
        raise NotImplementedError

    def write_metrics(self, metrics):
        raise NotImplementedError


class FileStorageBackend(StorageBackend):
    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.bars_path = self.root_dir / "bars.csv"
        self.news_path = self.root_dir / "news.csv"
        self.signals_path = self.root_dir / "signals.csv"
        self.fills_path = self.root_dir / "fills.csv"
        self.trades_path = self.root_dir / "trades.csv"
        self.system_path = self.root_dir / "system.log"
        self.metrics_path = self.root_dir / "metrics.json"
        self._initialize()

    def _initialize(self):
        self._init_csv(self.bars_path, [
            "timestamp",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "provider",
            "timeframe",
        ])
        self._init_csv(self.news_path, [
            "timestamp",
            "event_id",
            "symbol",
            "headline",
            "summary",
            "sentiment_score",
            "provider",
        ])
        self._init_csv(self.signals_path, [
            "timestamp",
            "symbol",
            "side",
            "score",
            "price",
            "metadata",
        ])
        self._init_csv(self.fills_path, [
            "timestamp",
            "order_id",
            "symbol",
            "side",
            "quantity",
            "requested_price",
            "fill_price",
            "slippage",
            "commission",
            "provider",
        ])
        self._init_csv(self.trades_path, [
            "symbol",
            "side",
            "entry_time",
            "exit_time",
            "entry_price",
            "exit_price",
            "quantity",
            "pnl",
            "reason",
            "entry_order_id",
            "exit_order_id",
        ])

    def _init_csv(self, path, headers):
        if path.exists():
            return
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)

    def store_bar(self, bar):
        self._append(self.bars_path, [
            bar.timestamp.isoformat(),
            bar.symbol,
            "%.2f" % bar.open,
            "%.2f" % bar.high,
            "%.2f" % bar.low,
            "%.2f" % bar.close,
            "%.0f" % bar.volume,
            bar.provider,
            bar.timeframe,
        ])

    def store_news(self, news):
        self._append(self.news_path, [
            news.timestamp.isoformat(),
            news.event_id,
            news.symbol,
            news.headline,
            news.summary,
            "%.4f" % news.sentiment_score,
            news.provider,
        ])

    def store_signal(self, signal):
        self._append(self.signals_path, [
            signal.timestamp.isoformat(),
            signal.symbol,
            signal.side,
            "%.4f" % signal.score,
            "%.2f" % signal.price,
            json.dumps(signal.metadata, sort_keys=True),
        ])

    def store_fill(self, fill):
        self._append(self.fills_path, [
            fill.timestamp.isoformat(),
            fill.order_id,
            fill.symbol,
            fill.side,
            fill.quantity,
            "%.2f" % fill.requested_price,
            "%.2f" % fill.fill_price,
            "%.4f" % fill.slippage,
            "%.4f" % fill.commission,
            fill.provider,
        ])

    def store_trade(self, trade):
        self._append(self.trades_path, [
            trade.symbol,
            trade.side,
            trade.entry_time.isoformat(),
            trade.exit_time.isoformat(),
            "%.2f" % trade.entry_price,
            "%.2f" % trade.exit_price,
            trade.quantity,
            "%.2f" % trade.pnl,
            trade.reason,
            trade.entry_order_id,
            trade.exit_order_id,
        ])

    def store_system_event(self, event_type, payload):
        line = "%s %s %s\n" % (datetime.utcnow().isoformat(), event_type, json.dumps(payload, sort_keys=True))
        with self.system_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _append(self, path, row):
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(row)

    def write_metrics(self, metrics):
        self.metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TimescaleStorageBackend(StorageBackend):
    def __init__(self, dsn):
        try:
            import psycopg
        except ImportError:
            raise RuntimeError("Install psycopg to use the TimescaleDB storage backend.")
        self.psycopg = psycopg
        self.conn = psycopg.connect(dsn)
        self.conn.autocommit = True

    def store_bar(self, bar):
        self._execute(
            "INSERT INTO market_bars (ts, symbol, open, high, low, close, volume, provider, timeframe) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (bar.timestamp, bar.symbol, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.provider, bar.timeframe),
        )

    def store_news(self, news):
        self._execute(
            "INSERT INTO news_events (ts, event_id, symbol, headline, summary, sentiment_score, provider) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (news.timestamp, news.event_id, news.symbol, news.headline, news.summary, news.sentiment_score, news.provider),
        )

    def store_signal(self, signal):
        self._execute(
            "INSERT INTO strategy_signals (ts, symbol, side, score, price, metadata) VALUES (%s,%s,%s,%s,%s,%s)",
            (signal.timestamp, signal.symbol, signal.side, signal.score, signal.price, json.dumps(signal.metadata, sort_keys=True)),
        )

    def store_fill(self, fill):
        self._execute(
            "INSERT INTO order_fills (ts, order_id, symbol, side, quantity, requested_price, fill_price, slippage, commission, provider) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (fill.timestamp, fill.order_id, fill.symbol, fill.side, fill.quantity, fill.requested_price, fill.fill_price, fill.slippage, fill.commission, fill.provider),
        )

    def store_trade(self, trade):
        self._execute(
            "INSERT INTO closed_trades (symbol, side, entry_time, exit_time, entry_price, exit_price, quantity, pnl, reason, entry_order_id, exit_order_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (trade.symbol, trade.side, trade.entry_time, trade.exit_time, trade.entry_price, trade.exit_price, trade.quantity, trade.pnl, trade.reason, trade.entry_order_id, trade.exit_order_id),
        )

    def store_system_event(self, event_type, payload):
        self._execute(
            "INSERT INTO system_events (ts, event_type, payload) VALUES (%s,%s,%s)",
            (datetime.utcnow(), event_type, json.dumps(payload, sort_keys=True)),
        )

    def write_metrics(self, metrics):
        self._execute(
            "INSERT INTO performance_metrics (ts, metrics) VALUES (%s,%s)",
            (datetime.utcnow(), json.dumps(metrics, sort_keys=True)),
        )

    def _execute(self, sql, params):
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)


TIMESCALE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS market_bars (
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    provider TEXT NOT NULL,
    timeframe TEXT NOT NULL
);
SELECT create_hypertable('market_bars', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS news_events (
    ts TIMESTAMPTZ NOT NULL,
    event_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT NOT NULL,
    sentiment_score DOUBLE PRECISION NOT NULL,
    provider TEXT NOT NULL
);
SELECT create_hypertable('news_events', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS order_fills (
    ts TIMESTAMPTZ NOT NULL,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    requested_price DOUBLE PRECISION NOT NULL,
    fill_price DOUBLE PRECISION NOT NULL,
    slippage DOUBLE PRECISION NOT NULL,
    commission DOUBLE PRECISION NOT NULL,
    provider TEXT NOT NULL
);
SELECT create_hypertable('order_fills', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS strategy_signals (
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    metadata JSONB NOT NULL
);
SELECT create_hypertable('strategy_signals', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS closed_trades (
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION NOT NULL,
    quantity INTEGER NOT NULL,
    pnl DOUBLE PRECISION NOT NULL,
    reason TEXT NOT NULL,
    entry_order_id TEXT NOT NULL,
    exit_order_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_events (
    ts TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL
);
SELECT create_hypertable('system_events', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS performance_metrics (
    ts TIMESTAMPTZ NOT NULL,
    metrics JSONB NOT NULL
);
SELECT create_hypertable('performance_metrics', 'ts', if_not_exists => TRUE);
""".strip()


def write_timescale_schema(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TIMESCALE_SCHEMA_SQL + "\n", encoding="utf-8")
