from __future__ import annotations

from datetime import timedelta
from statistics import mean

from trading_system.models import Signal


class MultiFactorStrategy(object):
    def __init__(self, config):
        self.config = config

    def generate_signals(self, bars_by_symbol, news_by_symbol, timestamp):
        scored = []
        for symbol, bars in bars_by_symbol.items():
            latest = bars[-1] if bars else None
            if latest is None or latest.timestamp != timestamp:
                continue
            regime = self._regime_state(bars)
            if regime is None or regime["is_tradeable"] is False:
                continue
            momentum_score = self._momentum_score(bars)
            breakout_score = self._breakout_score(bars)
            mean_reversion_score = self._mean_reversion_score(bars)
            if momentum_score is None or breakout_score is None or mean_reversion_score is None:
                continue
            news_score = self._news_score(news_by_symbol.get(symbol, []), timestamp)
            total_score = (
                momentum_score
                + (breakout_score * self.config.breakout_weight)
                + (mean_reversion_score * self.config.mean_reversion_weight)
                + (news_score * self.config.news_weight)
            )
            scored.append((symbol, latest, momentum_score, breakout_score, mean_reversion_score, news_score, regime, total_score))

        scored.sort(key=lambda item: item[7], reverse=True)
        signals = []
        for symbol, latest, momentum_score, breakout_score, mean_reversion_score, news_score, regime, total_score in scored[: self.config.max_symbols_considered]:
            if total_score < self.config.min_score:
                continue
            if news_score < self.config.min_news_sentiment:
                continue
            signals.append(
                Signal(
                    symbol=symbol,
                    timestamp=latest.timestamp,
                    side="BUY",
                    score=total_score,
                    price=latest.close,
                    metadata={
                        "momentum_score": momentum_score,
                        "breakout_score": breakout_score,
                        "mean_reversion_score": mean_reversion_score,
                        "news_score": news_score,
                        "regime_trend_strength": regime["trend_strength"],
                        "regime_choppiness": regime["choppiness"],
                        "close": latest.close,
                        "volume": latest.volume,
                    },
                )
            )
        return signals

    def should_exit(self, position, bars, timestamp):
        if not bars:
            return None
        latest = bars[-1]
        if latest.low <= position.stop_loss:
            return "stop_loss"
        if latest.high >= position.take_profit:
            return "take_profit"
        momentum_score = self._momentum_score(bars)
        regime = self._regime_state(bars)
        if momentum_score is not None and momentum_score < 0.8:
            return "momentum_break"
        if regime is not None and regime["is_tradeable"] is False:
            return "regime_change"
        return None

    def _regime_state(self, bars):
        if len(bars) < self.config.regime_window:
            return None
        window = bars[-self.config.regime_window :]
        closes = [bar.close for bar in window]
        highs = [bar.high for bar in window]
        lows = [bar.low for bar in window]
        start = closes[0]
        end = closes[-1]
        if start <= 0:
            return None
        trend_strength = abs((end / start) - 1.0)
        price_span = max(highs) - min(lows)
        directional_move = abs(end - start)
        if price_span <= 0:
            choppiness = 1.0
        else:
            choppiness = 1.0 - min(1.0, directional_move / price_span)
        return {
            "trend_strength": trend_strength,
            "choppiness": choppiness,
            "is_tradeable": trend_strength >= self.config.min_regime_trend_strength and choppiness <= self.config.max_choppiness,
        }

    def _momentum_score(self, bars):
        if len(bars) < self.config.slow_window:
            return None
        close = bars[-1].close
        if close < self.config.min_price or close > self.config.max_price:
            return None
        prices = [bar.close for bar in bars[-self.config.slow_window :]]
        volumes = [bar.volume for bar in bars[-self.config.volume_window :]]
        if len(volumes) < self.config.volume_window:
            return None
        fast_ma = mean(prices[-self.config.fast_window :])
        slow_ma = mean(prices)
        avg_volume = mean(volumes)
        if avg_volume <= 0 or fast_ma <= slow_ma:
            return None
        if bars[-1].volume < avg_volume * self.config.volume_multiplier:
            return None
        momentum = (fast_ma / slow_ma) - 1.0
        intrabar_strength = (bars[-1].close - bars[-1].open) / max(bars[-1].open, 0.01)
        relative_volume = bars[-1].volume / avg_volume
        return momentum * 100.0 + intrabar_strength * 10.0 + relative_volume

    def _breakout_score(self, bars):
        if len(bars) < self.config.breakout_window:
            return None
        window = bars[-self.config.breakout_window :]
        breakout_level = max(bar.high for bar in window[:-1])
        latest = window[-1]
        if breakout_level <= 0:
            return 0.0
        breakout_strength = max(0.0, (latest.close / breakout_level) - 1.0)
        return breakout_strength * 100.0

    def _mean_reversion_score(self, bars):
        if len(bars) < self.config.mean_reversion_window:
            return None
        window = bars[-self.config.mean_reversion_window :]
        closes = [bar.close for bar in window]
        avg_close = mean(closes)
        latest = closes[-1]
        if avg_close <= 0:
            return 0.0
        pullback = max(0.0, (avg_close - latest) / avg_close)
        return pullback * 25.0

    def _news_score(self, news_events, timestamp):
        cutoff = timestamp - timedelta(minutes=self.config.news_lookback_minutes)
        return sum(event.sentiment_score for event in news_events if event.timestamp >= cutoff)
