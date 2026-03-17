from __future__ import annotations
import pandas as pd
import ta


def ensure_ta(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()

    macd = ta.trend.MACD(close)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    bb = ta.volatility.BollingerBands(close, window=20)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_mid"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()

    df["atr"] = ta.volatility.AverageTrueRange(
        high, low, close, window=14
    ).average_true_range()

    df["vwap"] = (
        (df["close"] * df["volume"]).cumsum()
        / df["volume"].cumsum()
    )

    df["sma_20"] = ta.trend.SMAIndicator(close, window=20).sma_indicator()
    df["sma_50"] = ta.trend.SMAIndicator(close, window=50).sma_indicator()
    df["sma_200"] = ta.trend.SMAIndicator(close, window=200).sma_indicator()

    df["adx"] = ta.trend.ADXIndicator(high, low, close, window=14).adx()

    df["volume_sma_20"] = ta.trend.SMAIndicator(
        volume.astype(float), window=20
    ).sma_indicator()

    return df