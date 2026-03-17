from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Optional

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from trading_system.storage.models import MarketBar, NewsEvent, Signal
from trading_system.strategy.base import BaseStrategy
from trading_system.strategy.indicators import ensure_ta


class MLSignalStrategy(BaseStrategy):
    name = "ml_signal"

    def __init__(self, model_dir: Path, prediction_horizon: int = 5) -> None:
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.model_path = self.model_dir / "rf_model.joblib"
        self.prediction_horizon = prediction_horizon
        self.params = {"prediction_horizon": float(prediction_horizon)}
        self.warmup_periods = 50
        self._bars: dict[str, list[MarketBar]] = defaultdict(list)
        self.model = self._load_model()

    def __repr__(self) -> str:
        return f"MLSignalStrategy(model_path={str(self.model_path)!r}, prediction_horizon={self.prediction_horizon})"

    def _load_model(self) -> RandomForestClassifier:
        if self.model_path.exists():
            return joblib.load(self.model_path)
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        joblib.dump(model, self.model_path)
        return model

    def _feature_frame(self, bars: list[MarketBar]) -> pd.DataFrame:
        frame = pd.DataFrame([vars(item) for item in bars]).set_index("timestamp")
        frame = ensure_ta(frame)
        frame["volume_ratio"] = frame["volume"] / frame["volume"].rolling(20).mean().replace(0.0, 1.0)
        frame["hour"] = frame.index.hour
        frame["day_of_week"] = frame.index.dayofweek
        future_return = frame["close"].shift(-self.prediction_horizon) / frame["close"] - 1.0
        frame["target"] = (future_return >= 0.01).astype(int)
        return frame.dropna()

    def retrain(self, symbol: str) -> None:
        bars = self._bars[symbol]
        if len(bars) < 250:
            return
        frame = self._feature_frame(bars)
        if frame.empty:
            return
        features = frame[["returns_5", "returns_10", "returns_20", "rsi", "macd_hist", "atr", "volume_ratio", "hour", "day_of_week"]]
        target = frame["target"]
        if len(target.unique()) < 2:
            return
        self.model.fit(features, target)
        joblib.dump(self.model, self.model_path)

    def on_bar(self, bar: MarketBar) -> Optional[Signal]:
        history = self._bars[bar.symbol]
        history.append(bar)
        history[:] = history[-500:]
        if len(history) < self.warmup_periods:
            return None
        if len(history) % (5 * 78) == 0:
            self.retrain(bar.symbol)
        frame = self._feature_frame(history)
        if frame.empty or not hasattr(self.model, "classes_"):
            return None
        latest = frame.iloc[[-1]]
        features = latest[["returns_5", "returns_10", "returns_20", "rsi", "macd_hist", "atr", "volume_ratio", "hour", "day_of_week"]]
        probability = float(self.model.predict_proba(features)[0][1])
        if probability >= 0.6:
            return Signal(bar.symbol, "long", probability, self.name, f"ML probability={probability:.2f}", bar.timestamp)
        if probability <= 0.4:
            return Signal(bar.symbol, "short", 1.0 - probability, self.name, f"ML probability={probability:.2f}", bar.timestamp)
        return None

    def on_news(self, event: NewsEvent) -> Optional[Signal]:
        return None

