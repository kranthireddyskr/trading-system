from __future__ import annotations

import numpy as np
import pandas as pd


def ensure_ta(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        return result
    result["returns_5"] = result["close"].pct_change(5).fillna(0.0)
    result["returns_10"] = result["close"].pct_change(10).fillna(0.0)
    result["returns_20"] = result["close"].pct_change(20).fillna(0.0)
    delta = result["close"].diff().fillna(0.0)
    gain = delta.clip(lower=0.0).rolling(14).mean()
    loss = -delta.clip(upper=0.0).rolling(14).mean()
    rs = gain / loss.replace(0.0, np.nan)
    result["rsi"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)
    ema12 = result["close"].ewm(span=12, adjust=False).mean()
    ema26 = result["close"].ewm(span=26, adjust=False).mean()
    result["macd"] = ema12 - ema26
    result["macd_signal"] = result["macd"].ewm(span=9, adjust=False).mean()
    result["macd_hist"] = result["macd"] - result["macd_signal"]
    basis = result["close"].rolling(20).mean()
    dev = result["close"].rolling(20).std(ddof=0).fillna(0.0)
    result["bb_mid"] = basis.fillna(result["close"])
    result["bb_upper"] = (basis + (2 * dev)).fillna(result["close"])
    result["bb_lower"] = (basis - (2 * dev)).fillna(result["close"])
    result["atr"] = atr(result)
    result["adx"] = adx(result)
    return result


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = frame["high"] - frame["low"]
    high_close = (frame["high"] - frame["close"].shift()).abs()
    low_close = (frame["low"] - frame["close"].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(period).mean().fillna(method="bfill").fillna(0.0)


def adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = frame["high"].diff()
    down_move = -frame["low"].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    true_range = atr(frame, period).replace(0.0, np.nan)
    plus_di = 100 * (plus_dm.rolling(period).mean() / true_range)
    minus_di = 100 * (minus_dm.rolling(period).mean() / true_range)
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)) * 100
    return dx.rolling(period).mean().fillna(10.0)

