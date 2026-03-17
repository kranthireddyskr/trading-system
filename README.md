# Trading System

This project is a production-style algorithmic day trading platform in Python with:

- Alpaca WebSocket and REST market data
- strategy portfolio with momentum, mean reversion, and ML signals
- risk limits, drawdown monitoring, and correlation checks
- Alpaca broker integration and paper execution
- event-driven backtesting with metrics and HTML report
- TimescaleDB storage with CSV fallback
- Flask dashboard, heartbeat, and email alerts

## Project Layout

```text
trading_system/
├── data/
├── strategy/
├── risk/
├── execution/
├── backtest/
├── storage/
├── monitoring/
├── config/
├── agent.py
├── backtest_runner.py
├── live_runner.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Environment

Copy `.env.example` to `.env` and set values, or rely on AWS Secrets Manager with `SECRETS_MANAGER_SECRET_ID`.

Secrets load order:

1. AWS Secrets Manager
2. Environment variables

## Live Trading

Paper or dry-run mode:

```powershell
python .\live_runner.py --watchlist .\trading_system\config\watchlist.txt --output-dir .\live_logs --dry-run --paper
```

Live broker mode:

```powershell
python .\live_runner.py --watchlist .\trading_system\config\watchlist.txt --output-dir .\live_logs --live
```

Dashboard:

- `http://localhost:8080/`
- `http://localhost:8080/health`
- `http://localhost:8080/metrics`

## Backtesting

```powershell
python .\backtest_runner.py --start-date 2026-01-02T09:30:00Z --end-date 2026-01-10T16:00:00Z --strategy all --output-dir .\backtest_results
```

Outputs:

- `backtest_report.html`
- metrics printed to the terminal

## Docker

```powershell
docker compose up --build
```

This starts:

- `trading-bot`
- `timescaledb`

## Notes

- `watchlist.txt` is stored with UTF-8 BOM-safe handling
- all trading decisions check regular US market hours before orders
- Alpaca news failures return empty lists and do not crash the system
- WebSocket feed reconnects automatically and falls back to REST polling
