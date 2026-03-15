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
