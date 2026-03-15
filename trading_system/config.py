from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class StrategyConfig:
    fast_window: int = 3
    slow_window: int = 6
    volume_window: int = 5
    volume_multiplier: float = 1.1
    breakout_window: int = 8
    mean_reversion_window: int = 6
    min_price: float = 5.0
    max_price: float = 500.0
    min_score: float = 1.15
    news_weight: float = 0.35
    breakout_weight: float = 0.3
    mean_reversion_weight: float = 0.2
    news_lookback_minutes: int = 90
    min_news_sentiment: float = -2.0
    max_symbols_considered: int = 5
    regime_window: int = 12
    min_regime_trend_strength: float = 0.0025
    max_choppiness: float = 0.75


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3
    max_position_notional_pct: float = 0.2
    max_symbol_exposure_pct: float = 0.2
    stop_loss_pct: float = 0.003
    take_profit_pct: float = 0.006
    max_trades_per_day: int = 5
    halt_on_data_failure: bool = True
    halt_on_broker_failure: bool = True


@dataclass
class RuntimeConfig:
    poll_seconds: int = 20
    news_poll_seconds: int = 60
    data_feed: str = "iex"
    output_dir: Path = Path("runtime_logs")
    dry_run: bool = False
    max_loops: int = 0


@dataclass
class StorageConfig:
    backend: str = "file"
    postgres_dsn: str = ""
    file_dir: Path = Path("runtime_logs")


@dataclass
class MonitoringConfig:
    heartbeat_path: Path = Path("runtime_logs/heartbeat.json")
    dashboard_path: Path = Path("runtime_logs/dashboard.json")
    alerts_path: Path = Path("runtime_logs/alerts.log")
    alert_webhook_url: str = ""
