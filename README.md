# Trading System

This workspace is now structured as a modular trading system with:

- normalized historical and live market data ingestion
- a multi-factor, regime-aware strategy layer
- paper and broker-routed execution
- risk controls and circuit breakers
- backtest metrics and equity-curve output
- monitoring artifacts and alert hooks
- file storage by default, with TimescaleDB wiring available

## Project layout

- `trading_system/data.py`: CSV history loader and Alpaca data clients
- `trading_system/strategy.py`: multi-factor strategy with regime detection
- `trading_system/risk.py`: sizing, drawdown, and position-limit logic
- `trading_system/execution.py`: simulated paper fills and Alpaca broker execution
- `trading_system/storage.py`: file storage and TimescaleDB storage backend
- `trading_system/analytics.py`: Sharpe, Sortino, drawdown, win/loss, and equity-curve reporting
- `trading_system/monitoring.py`: heartbeat, dashboard snapshots, and alerts
- `trading_system/secrets.py`: environment, JSON secret file, and AWS Secrets Manager support
- `trading_agent.py`: historical replay / backtesting entry point
- `alpaca_paper_bot.py`: live paper-trading entry point

## Backtesting

Run the backtest engine over local OHLCV CSV files:

```powershell
python .\trading_agent.py paper-auto --data-dir .\sample_watchlist_data --output-dir .\logs
```

Artifacts written to the output directory:

- `bars.csv`
- `signals.csv`
- `fills.csv`
- `trades.csv`
- `system.log`
- `equity_curve.csv`
- `metrics.txt`
- `metrics.json`
- `timescale_schema.sql`

The backtest summary now includes:

- Sharpe ratio
- Sortino ratio
- win rate
- average win and average loss
- profit factor
- max drawdown
- ending cash

## Strategy model

The strategy is no longer just momentum plus keyword news. It now combines:

- momentum scoring
- breakout scoring
- pullback / mean-reversion scoring
- news sentiment scoring
- regime filtering based on trend strength and choppiness

This still does not guarantee live edge. You should treat it as a stronger baseline and only promote a parameter set to live after the backtest metrics meet your thresholds, such as Sharpe above `1.5`.

## Live trading

Run the live paper trader:

```powershell
python .\alpaca_paper_bot.py --watchlist .\watchlist.txt --output-dir .\live_logs
```

Useful flags:

- `--dry-run`: consume live data but simulate fills locally
- `--postgres-dsn ...`: write runtime events directly into TimescaleDB / Postgres
- `--session regular|extended`: allow only regular-hours or extended-hours trading
- `--exit-after-close`: stop after the allowed session ends
- `--alert-webhook-url ...`: send alert payloads to a webhook when circuit breakers fire
- `--max-loops 5`: run a short smoke test

## Monitoring and alerting

The live process now writes:

- `heartbeat.json`: liveness and current state
- `dashboard.json`: a simple real-time P&L snapshot
- `alerts.log`: alert events including circuit-breaker conditions
- `system.log`: loop and runtime events

This is enough to integrate with external monitoring or a small UI. For production recovery, run the bot under `systemd`, `supervisord`, or a container orchestrator with restart policies and health checks.

## Storage

Default storage is file-based so the project runs immediately.

If you provide `--postgres-dsn` or set `TIMESCALE_POSTGRES_DSN`, the project will use the TimescaleDB/Postgres storage backend and write directly into:

- `market_bars`
- `news_events`
- `strategy_signals`
- `order_fills`
- `closed_trades`
- `system_events`
- `performance_metrics`

The schema starter is still generated for bootstrap workflows.

## Secrets management

Credential resolution order is now:

1. environment variables such as `APCA_API_KEY_ID`
2. `TRADING_SECRET_FILE` JSON file
3. AWS Secrets Manager via `AWS_SECRETS_MANAGER_SECRET_ID`

This lets you move away from ad-hoc shell-only secrets for cloud deployment.

## Scheduling and market hours

The process now understands:

- regular session: `9:30 AM` to `4:00 PM` market time behavior through broker clock plus session filter
- extended session support through `--session extended`
- optional stop-after-close behavior with `--exit-after-close`

For automated start and stop, use:

- AWS EventBridge on EC2/ECS
- cron on a VM
- container platform scheduled jobs

## Concurrency

The live path already batches watchlist snapshots in a single Alpaca snapshot request, which is better than fetching symbols one by one.

On top of that, the runtime now parallelizes broker clock and market-data retrieval with a thread pool so the loop spends less time waiting on sequential network I/O.

## Dependencies

Core:

```powershell
pip install -r .\requirements.txt
```

Optional extras:

- `psycopg`: required for TimescaleDB/Postgres runtime storage
- `boto3`: required for AWS Secrets Manager loading
- `websocket-client`: required if you later finish the websocket streaming path

## Remaining limitations

- websocket streaming is still scaffolded rather than fully wired
- there is not yet a graphical dashboard; monitoring is file- and webhook-based
- strategy validation is still your responsibility; the code now reports the metrics needed to decide whether it is good enough
