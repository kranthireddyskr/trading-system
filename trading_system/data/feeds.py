from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Optional

import requests
import websocket

from trading_system.data.normalizer import normalize_bar
from trading_system.storage.models import MarketBar


class AlpacaWebSocketFeed:
    def __init__(self, api_key: str, api_secret: str, symbols: list[str], output_queue: queue.Queue, logger: logging.Logger) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = symbols
        self.output_queue = output_queue
        self.logger = logger
        self._stop_event = threading.Event()
        self._socket_app: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._rest_headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}

    def __repr__(self) -> str:
        return f"AlpacaWebSocketFeed(symbols={self.symbols!r})"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._socket_app is not None:
            self._socket_app.close()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        backoff = 1
        while not self._stop_event.is_set():
            try:
                self._socket_app = websocket.WebSocketApp(
                    "wss://stream.data.alpaca.markets/v2/iex",
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._socket_app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                self.logger.exception("WebSocket loop failed: %s", exc)
            if self._stop_event.is_set():
                break
            self.logger.warning("WebSocket disconnected, retrying in %s seconds", backoff)
            self._rest_poll_once()
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        ws.send(json.dumps({"action": "auth", "key": self.api_key, "secret": self.api_secret}))
        ws.send(json.dumps({"action": "subscribe", "bars": self.symbols, "quotes": self.symbols, "trades": self.symbols}))
        self.logger.info("WebSocket opened and subscriptions sent")

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        try:
            events = json.loads(message)
        except json.JSONDecodeError:
            self.logger.warning("Ignoring invalid websocket payload")
            return
        for event in events:
            event_type = event.get("T")
            if event_type == "b":
                bar = normalize_bar(event, event["S"], "websocket")
                self.output_queue.put(bar)
            elif event_type in {"success", "subscription"}:
                self.logger.info("WebSocket event: %s", event)
            elif event_type == "error":
                self.logger.error("WebSocket error payload: %s", event)

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        self.logger.error("WebSocket error: %s", error)

    def _on_close(self, ws: websocket.WebSocketApp, status_code: int, message: str) -> None:
        self.logger.warning("WebSocket closed status=%s message=%s", status_code, message)

    def _rest_poll_once(self) -> None:
        try:
            response = requests.get(
                "https://data.alpaca.markets/v2/stocks/snapshots",
                headers=self._rest_headers,
                params={"symbols": ",".join(self.symbols), "feed": "iex"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            for symbol in self.symbols:
                snapshot = payload.get(symbol)
                if not snapshot or "minuteBar" not in snapshot:
                    continue
                bar = normalize_bar(snapshot["minuteBar"], symbol, "rest")
                self.output_queue.put(bar)
        except Exception as exc:
            self.logger.exception("REST fallback failed: %s", exc)
