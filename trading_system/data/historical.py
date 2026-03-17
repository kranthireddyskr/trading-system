from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import requests


class HistoricalDataLoader:
    def __init__(self, api_key: str, api_secret: str, cache_dir: Path) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = "https://data.alpaca.markets/v2/stocks/bars"

    def __repr__(self) -> str:
        return f"HistoricalDataLoader(cache_dir={str(self.cache_dir)!r})"

    def load(self, symbol: str, start: str, end: str, timeframe: str = "1Min") -> pd.DataFrame:
        cache_path = self.cache_dir / f"{symbol}_{timeframe}_{start}_{end}.csv".replace(":", "-")
        if cache_path.exists():
            frame = pd.read_csv(cache_path, parse_dates=["timestamp"], index_col="timestamp")
            return frame

        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }
        params = {
            "symbols": symbol,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "limit": 10000,
            "adjustment": "raw",
            "feed": "iex",
        }
        response = requests.get(self.base_url, headers=headers, params=params, timeout=30)
        if response.status_code == 401:
            raise RuntimeError("Alpaca historical data request was unauthorized. Set valid APCA_API_KEY_ID and APCA_API_SECRET_KEY before running backtests.")
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("bars", {}).get(symbol, [])
        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "vwap"])
        frame = frame.rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "vw": "vwap"})
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.set_index("timestamp")
        frame.to_csv(cache_path)
        return frame
