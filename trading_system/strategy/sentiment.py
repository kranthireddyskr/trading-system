from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests

from trading_system.storage.models import MarketBar
from trading_system.strategy.indicators import ensure_ta

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]


_POSITIVE_KEYWORDS = frozenset(
    ["beat", "beats", "surge", "surges", "strong", "record", "breakout", "upgrade", "raised", "outperform", "rally", "profit", "growth"]
)
_NEGATIVE_KEYWORDS = frozenset(
    ["miss", "misses", "miss", "decline", "weak", "cut", "downgrade", "warning", "loss", "recall", "lawsuit", "investigation", "fraud", "layoff", "layoffs"]
)

_CACHE_TTL_SECONDS = 300  # 5 minutes


@dataclass
class SentimentScore:
    symbol: str
    score: float  # composite, range [-1, 1]
    news_score: float
    technical_score: float
    regime_score: float
    vix_score: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __repr__(self) -> str:
        return f"SentimentScore(symbol={self.symbol!r}, score={self.score:.3f}, news={self.news_score:.2f}, tech={self.technical_score:.2f})"


class SentimentAnalyzer:
    """Four-source composite sentiment scorer with 5-minute per-symbol caching.

    Sources and weights:
        news        35%  – Alpaca news API keyword scoring
        technical   30%  – RSI / MA / MACD / volume alignment
        regime      20%  – SPY trend (MA50 vs MA200 + daily return)
        vix_proxy   15%  – SPY realized volatility as VIX proxy (high vol → bearish)
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        bar_history: dict[str, list[MarketBar]],
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.bar_history = bar_history
        self._cache: dict[str, tuple[float, SentimentScore]] = {}  # symbol → (expiry_ts, score)
        self.logger = logging.getLogger("trading_system.sentiment")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_composite_sentiment(self, symbol: str) -> SentimentScore:
        """Return composite sentiment, using cached result if still fresh."""
        cached_expiry, cached_score = self._cache.get(symbol, (0.0, None))  # type: ignore[assignment]
        if cached_score is not None and time.monotonic() < cached_expiry:
            return cached_score

        news = self.get_news_sentiment(symbol)
        technical = self.get_technical_sentiment(symbol)
        regime = self.get_market_regime_sentiment()
        vix = self.get_vix_sentiment()

        composite = round(news * 0.35 + technical * 0.30 + regime * 0.20 + vix * 0.15, 4)
        composite = max(-1.0, min(1.0, composite))

        score = SentimentScore(
            symbol=symbol,
            score=composite,
            news_score=news,
            technical_score=technical,
            regime_score=regime,
            vix_score=vix,
        )
        self._cache[symbol] = (time.monotonic() + _CACHE_TTL_SECONDS, score)
        self.logger.debug("Sentiment %s: composite=%.3f news=%.2f tech=%.2f regime=%.2f vix=%.2f", symbol, composite, news, technical, regime, vix)
        return score

    # ------------------------------------------------------------------
    # Source 1 – News (35%)
    # ------------------------------------------------------------------

    def get_news_sentiment(self, symbol: str) -> float:
        """Query Alpaca news API; score headlines by keyword presence.

        Returns a float in [-1, 1].  Returns 0.0 on any failure.
        """
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }
        try:
            response = requests.get(
                "https://data.alpaca.markets/v1beta1/news",
                headers=headers,
                params={"symbols": symbol, "limit": 10, "sort": "desc"},
                timeout=10,
            )
            response.raise_for_status()
            articles: list[dict[str, Any]] = response.json().get("news", [])
        except Exception as exc:
            self.logger.debug("News fetch failed for %s: %s", symbol, exc)
            return 0.0

        if not articles:
            return 0.0

        scores: list[float] = []
        for article in articles:
            text = (article.get("headline", "") + " " + article.get("summary", "")).lower()
            words = set(text.split())
            pos_hits = len(words & _POSITIVE_KEYWORDS)
            neg_hits = len(words & _NEGATIVE_KEYWORDS)
            raw = (pos_hits - neg_hits) / max(pos_hits + neg_hits, 1)
            scores.append(max(-1.0, min(1.0, raw)))

        return round(sum(scores) / len(scores), 4)

    # ------------------------------------------------------------------
    # Source 2 – Technical (30%)
    # ------------------------------------------------------------------

    def get_technical_sentiment(self, symbol: str) -> float:
        """Score technical alignment: RSI, MA crossover, MACD, volume ratio.

        Returns a float in [-1, 1].  Returns 0.0 if insufficient history.
        """
        history = self.bar_history.get(symbol, [])
        if len(history) < 14:
            return 0.0

        try:
            import pandas as _pd
        except ImportError:
            return 0.0

        try:
            frame = _pd.DataFrame([vars(b) for b in history]).set_index("timestamp")
            frame = ensure_ta(frame)
        except Exception as exc:
            self.logger.debug("Technical sentiment failed for %s: %s", symbol, exc)
            return 0.0

        latest = frame.iloc[-1]
        score = 0.0
        components = 0

        # RSI: <45 bullish, >55 bearish
        rsi = float(latest.get("rsi", 50))
        score += max(-1.0, min(1.0, (50 - rsi) / 30))
        components += 1

        # Price vs VWAP
        vwap = float(latest.get("vwap", latest["close"]))
        close = float(latest["close"])
        score += 1.0 if close > vwap else -1.0
        components += 1

        # MACD histogram direction
        macd_hist = float(latest.get("macd_hist", 0))
        score += 1.0 if macd_hist > 0 else (-1.0 if macd_hist < 0 else 0.0)
        components += 1

        # Price above BB upper → bullish breakout; below BB lower → bearish
        bb_upper = float(latest.get("bb_upper", close * 1.02))
        bb_lower = float(latest.get("bb_lower", close * 0.98))
        if close > bb_upper:
            score += 0.5
        elif close < bb_lower:
            score -= 0.5
        components += 1

        if components == 0:
            return 0.0
        return round(max(-1.0, min(1.0, score / components)), 4)

    # ------------------------------------------------------------------
    # Source 3 – Market regime via SPY (20%)
    # ------------------------------------------------------------------

    def get_market_regime_sentiment(self) -> float:
        """Use SPY bar history to gauge broad market regime.

        Bullish if SPY MA50 > MA200 and recent return positive.
        Returns a float in [-1, 1].
        """
        spy_history = self.bar_history.get("SPY", [])
        if len(spy_history) < 50:
            return 0.0

        closes = [b.close for b in spy_history]
        ma50 = sum(closes[-50:]) / 50
        ma200 = sum(closes[-200:]) / len(closes[-200:])

        # Trend component
        trend = 1.0 if ma50 > ma200 else -1.0

        # Short-term momentum: compare last close to 5 bars ago
        recent_return = (closes[-1] - closes[-6]) / max(closes[-6], 0.01) if len(closes) >= 6 else 0.0
        momentum = max(-1.0, min(1.0, recent_return * 20))  # scale ±5% → ±1

        return round((trend * 0.6 + momentum * 0.4), 4)

    # ------------------------------------------------------------------
    # Source 4 – VIX proxy via SPY realized vol (15%)
    # ------------------------------------------------------------------

    def get_vix_sentiment(self) -> float:
        """Use SPY 20-bar realized volatility as a VIX proxy.

        High vol → risk-off → negative sentiment.
        Returns a float in [-1, 1].
        """
        spy_history = self.bar_history.get("SPY", [])
        if len(spy_history) < 21:
            return 0.0

        closes = [b.close for b in spy_history[-21:]]
        returns = [(closes[i] - closes[i - 1]) / max(closes[i - 1], 0.01) for i in range(1, len(closes))]
        if not returns:
            return 0.0

        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        realized_vol = variance ** 0.5 * (252 ** 0.5)  # annualized

        # Typical SPY annualized vol: ~15%.  >25% = high fear.
        if realized_vol < 0.10:
            return 0.5   # very low vol → risk-on
        if realized_vol < 0.18:
            return 0.2   # normal vol → mildly bullish
        if realized_vol < 0.25:
            return -0.2  # elevated vol → mildly bearish
        return -0.8      # high vol → risk-off
