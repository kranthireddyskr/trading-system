from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Iterable, List

import requests


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

