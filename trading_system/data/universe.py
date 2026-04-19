from __future__ import annotations

import logging
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Iterable, List, Optional

import requests


# ---------------------------------------------------------------------------
# Dynamic universe selector
# ---------------------------------------------------------------------------

_SECTOR_MAP: dict[str, str] = {}  # populated lazily; symbol → sector

_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "NVDA", "AMD", "GOOGL", "META", "AMZN", "TSLA", "NFLX", "ADBE", "CRM", "ORCL", "INTC", "QCOM", "AVGO", "TXN", "MU", "AMAT", "LRCX", "KLAC"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "BMY", "AMGN", "GILD", "CVS", "CI", "HUM", "MDT", "ABT", "TMO", "DHR", "ISRG", "REGN", "VRTX", "ZTS"],
    "Financials": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "C", "AXP", "USB", "PNC", "SCHW", "COF", "TFC", "BK", "STT", "ICE", "CME", "CB", "MET", "PRU"],
    "Consumer": ["HD", "MCD", "NKE", "SBUX", "TGT", "WMT", "COST", "LOW", "TJX", "ROST", "YUM", "CMG", "DG", "DLTR", "KR", "AZO", "ORLY", "BBY", "ETSY", "EBAY"],
    "Industrials": ["BA", "CAT", "GE", "MMM", "HON", "RTX", "LMT", "NOC", "DE", "EMR", "ETN", "ITW", "FDX", "UPS", "CSX", "UNP", "NSC", "WM", "RSG", "PCAR"],
    "Energy": ["XOM", "CVX", "COP", "PXD", "EOG", "SLB", "MPC", "VLO", "PSX", "OXY", "HES", "DVN", "FANG", "HAL", "BKR", "KMI", "WMB", "OKE", "ET", "TRGP"],
    "Materials": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "STLD", "CF", "MOS", "ALB", "DD", "PPG", "IFF", "FMC", "CE", "EMN", "AVNT", "OLN", "WLK"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "XEL", "ED", "WEC", "ETR", "FE", "PPL", "CMS", "DTE", "AEE", "CNP", "NI", "PNW", "EVRG", "OGE"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "WELL", "AVB", "EQR", "DLR", "VICI", "IRM", "BXP", "ARE", "ESS", "MAA", "UDR", "CPT", "EXR"],
    "Communications": ["T", "VZ", "CMCSA", "CHTR", "TMUS", "DIS", "PARA", "WBD", "FOX", "FOXA"],
}

# Build reverse lookup: symbol → sector
_SYMBOL_TO_SECTOR: dict[str, str] = {}
for _sector, _syms in _SECTOR_KEYWORDS.items():
    for _sym in _syms:
        _SYMBOL_TO_SECTOR[_sym] = _sector


def _infer_sector(symbol: str) -> str:
    return _SYMBOL_TO_SECTOR.get(symbol, "Other")


class UniverseSelector:
    """Dynamically select 50-100 liquid, sector-balanced US equities each day.

    Algorithm:
        1. Fetch all active, tradable US equity assets from Alpaca.
        2. Filter: price > ``min_price`` AND avg daily volume > ``min_avg_volume``.
        3. Score each remaining symbol by ``volume × volatility`` (high-activity stocks).
        4. Group by sector; take at most ``max_per_sector`` symbols per sector.
        5. Return the top ``universe_size`` symbols globally.

    Results are cached for ``cache_ttl_seconds`` (default 24 h) so the network
    call only happens once per day.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        universe_size: int = 50,
        min_price: float = 10.0,
        min_avg_volume: int = 1_000_000,
        max_per_sector: int = 10,
        cache_ttl_seconds: int = 86_400,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.universe_size = universe_size
        self.min_price = min_price
        self.min_avg_volume = min_avg_volume
        self.max_per_sector = max_per_sector
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: list[str] = []
        self._cache_expiry: float = 0.0
        self._lock = Lock()
        self.logger = logging.getLogger("trading_system.universe")

    def __repr__(self) -> str:
        return (
            f"UniverseSelector(universe_size={self.universe_size}, "
            f"min_price={self.min_price}, min_avg_volume={self.min_avg_volume})"
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    def select(self) -> list[str]:
        """Return cached universe or refresh it if stale."""
        with self._lock:
            if self._cache and time.monotonic() < self._cache_expiry:
                return list(self._cache)
            symbols = self._build_universe()
            self._cache = symbols
            self._cache_expiry = time.monotonic() + self.cache_ttl_seconds
            return list(symbols)

    def _build_universe(self) -> list[str]:
        """Fetch assets, apply filters, sector-balance, return top N."""
        self.logger.info("Building dynamic universe (min_price=%.0f, min_volume=%s)", self.min_price, self.min_avg_volume)

        assets = self._fetch_assets()
        if not assets:
            self.logger.warning("No assets fetched; returning empty universe")
            return []

        # Filter by price and estimated daily volume using last quote snapshot
        scored: list[tuple[float, str]] = []
        for asset in assets:
            symbol: str = asset.get("symbol", "")
            if not symbol or not asset.get("tradable", False):
                continue
            # Score = close * volume (proxy for liquidity × activity)
            # We use the snapshot endpoint for a quick price/volume check
            price, volume, volatility = self._get_snapshot(symbol)
            if price < self.min_price or volume < self.min_avg_volume:
                continue
            score = volume * volatility  # higher = more activity
            scored.append((score, symbol))

        if not scored:
            self.logger.warning("No symbols passed filters; universe will be empty")
            return []

        scored.sort(reverse=True)

        # Sector-balanced selection
        sector_counts: dict[str, int] = defaultdict(int)
        selected: list[str] = []
        for _score, symbol in scored:
            if len(selected) >= self.universe_size:
                break
            sector = _infer_sector(symbol)
            if sector_counts[sector] >= self.max_per_sector:
                continue
            selected.append(symbol)
            sector_counts[sector] += 1

        self.logger.info(
            "Universe built: %d symbols across %d sectors",
            len(selected),
            len(sector_counts),
        )
        return selected

    def _fetch_assets(self) -> list[dict]:
        """Fetch all active, tradable US equity assets from Alpaca."""
        try:
            response = requests.get(
                "https://paper-api.alpaca.markets/v2/assets",
                headers=self._headers,
                params={"status": "active", "asset_class": "us_equity"},
                timeout=30,
            )
            response.raise_for_status()
            return [a for a in response.json() if a.get("tradable") and a.get("fractionable", True)]
        except Exception as exc:
            self.logger.warning("Failed to fetch assets: %s", exc)
            return []

    def _get_snapshot(self, symbol: str) -> tuple[float, float, float]:
        """Return (price, volume, volatility) from Alpaca snapshot.

        Falls back to (0.0, 0.0, 0.0) on any error so the symbol is filtered out.
        """
        try:
            response = requests.get(
                f"https://data.alpaca.markets/v2/stocks/{symbol}/snapshot",
                headers=self._headers,
                params={"feed": "iex"},
                timeout=10,
            )
            if response.status_code != 200:
                return 0.0, 0.0, 0.0
            data = response.json()
            daily_bar = data.get("dailyBar") or data.get("prevDailyBar") or {}
            price = float(daily_bar.get("c", 0))
            volume = float(daily_bar.get("v", 0))
            high = float(daily_bar.get("h", price))
            low = float(daily_bar.get("l", price))
            volatility = (high - low) / max(price, 0.01)
            return price, volume, volatility
        except Exception:
            return 0.0, 0.0, 0.0


# ---------------------------------------------------------------------------
# Static watchlist-backed universe (unchanged original)
# ---------------------------------------------------------------------------


class SymbolUniverse:
    def __init__(self, watchlist_path: Path, api_key: str, api_secret: str) -> None:
        self.watchlist_path = Path(watchlist_path)
        self.api_key = api_key
        self.api_secret = api_secret
        self._symbols: list[str] = []
        self._lock = Lock()
        self.reload()

    def __repr__(self) -> str:
        return f"SymbolUniverse(watchlist_path={str(self.watchlist_path)!r}, symbols={self._symbols!r})"

    def reload(self) -> list[str]:
        with self._lock:
            content = self.watchlist_path.read_text(encoding="utf-8-sig")
            symbols = []
            for line in content.splitlines():
                symbol = line.strip().upper().replace("\ufeff", "")
                if symbol:
                    symbols.append(symbol)
            self._symbols = self.validate(symbols)
            return list(self._symbols)

    def symbols(self) -> list[str]:
        with self._lock:
            return list(self._symbols)

    def update(self, symbols: Iterable[str]) -> list[str]:
        clean = [str(symbol).strip().upper().replace("\ufeff", "") for symbol in symbols if str(symbol).strip()]
        with self.watchlist_path.open("w", encoding="utf-8-sig") as handle:
            handle.write("\n".join(clean) + "\n")
        return self.reload()

    def validate(self, symbols: list[str]) -> list[str]:
        if not symbols:
            return []
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }
        try:
            response = requests.get("https://paper-api.alpaca.markets/v2/assets", headers=headers, params={"status": "active"}, timeout=20)
            response.raise_for_status()
            active = {asset["symbol"] for asset in response.json() if asset.get("tradable")}
            return [symbol for symbol in symbols if symbol in active]
        except Exception:
            return symbols

