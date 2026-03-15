from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import requests

from trading_system.models import MarketBar, NewsEvent
from trading_system.utils import headline_sentiment, parse_timestamp


DATA_URL = "https://data.alpaca.markets"


class CsvHistoricalDataProvider(object):
    def load_bars(self, data_dir):
        bars = []
        for csv_path in sorted(Path(data_dir).glob("*.csv")):
            with csv_path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    symbol = row.get("symbol") or row.get("\ufeffsymbol") or csv_path.stem.upper()
                    bars.append(MarketBar(
                        symbol=symbol,
                        timestamp=datetime.fromisoformat(self._field(row, "timestamp")),
                        open=float(self._field(row, "open")),
                        high=float(self._field(row, "high")),
                        low=float(self._field(row, "low")),
                        close=float(self._field(row, "close")),
                        volume=float(self._field(row, "volume")),
                        provider="csv",
                        timeframe="1Min",
                    ))
        bars.sort(key=lambda bar: (bar.timestamp, bar.symbol))
        return bars

    def grouped_bars(self, data_dir):
        grouped = defaultdict(list)
        for bar in self.load_bars(data_dir):
            grouped[bar.timestamp].append(bar)
        return sorted(grouped.items(), key=lambda item: item[0])

    def _field(self, row, name):
        if name in row:
            return row[name]
        bom_name = "\ufeff%s" % name
        if bom_name in row:
            return row[bom_name]
        raise KeyError(name)


class AlpacaMarketDataClient(object):
    def __init__(self, api_key, api_secret, data_feed="iex"):
        self.data_feed = data_feed
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Content-Type": "application/json",
        })

    def get_snapshots(self, symbols):
        params = {"symbols": ",".join(symbols), "feed": self.data_feed}
        response = self.session.get(DATA_URL + "/v2/stocks/snapshots", params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        bars = []
        for symbol in symbols:
            snapshot = payload.get(symbol)
            if not snapshot or not snapshot.get("minuteBar"):
                continue
            minute_bar = snapshot["minuteBar"]
            bars.append(MarketBar(
                symbol=symbol,
                timestamp=parse_timestamp(minute_bar["t"]),
                open=float(minute_bar["o"]),
                high=float(minute_bar["h"]),
                low=float(minute_bar["l"]),
                close=float(minute_bar["c"]),
                volume=float(minute_bar["v"]),
                provider="alpaca_rest",
                timeframe="1Min",
            ))
        return bars

    def get_news(self, symbols, now, lookback_minutes=90, limit=50):
        params = {
            "symbols": ",".join(symbols),
            "start": (now - timedelta(minutes=lookback_minutes)).isoformat() + "Z",
            "limit": limit,
            "sort": "desc",
        }
        response = self.session.get(DATA_URL + "/v1beta1/news", params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        events = []
        for article in payload.get("news", []):
            created_at = parse_timestamp(article["created_at"])
            headline = article.get("headline", "")
            summary = article.get("summary", "")
            sentiment = headline_sentiment(headline + " " + summary)
            for symbol in article.get("symbols", []):
                events.append(NewsEvent(
                    event_id=str(article["id"]),
                    symbol=symbol,
                    timestamp=created_at,
                    headline=headline,
                    summary=summary,
                    sentiment_score=sentiment,
                    provider="alpaca_news",
                ))
        return events


class AlpacaWebSocketMarketDataFeed(object):
    def __init__(self, api_key, api_secret, symbols, feed="iex"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = symbols
        self.feed = feed

    def connect(self):
        try:
            import websocket
        except ImportError:
            raise RuntimeError("Install websocket-client to enable Alpaca websocket market data streaming.")
        raise NotImplementedError(
            "WebSocket scaffolding is configured conceptually, but message loop handling still depends on your deployment choices."
        )
