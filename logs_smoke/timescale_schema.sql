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
