from __future__ import annotations

import threading
import time
from typing import Callable

from flask import Flask, jsonify


class DashboardServer:
    def __init__(self, state_provider: Callable[[], dict], port: int = 8080) -> None:
        self.state_provider = state_provider
        self.port = port
        self.app = Flask(__name__)
        self.started_at = time.time()
        self._thread: threading.Thread | None = None
        self._register_routes()

    def __repr__(self) -> str:
        return f"DashboardServer(port={self.port})"

    def _register_routes(self) -> None:
        @self.app.get("/health")
        def health():
            return jsonify({"status": "ok", "uptime": round(time.time() - self.started_at, 2)})

        @self.app.get("/metrics")
        def metrics():
            return jsonify(self.state_provider().get("metrics", {}))

        @self.app.get("/positions")
        def positions():
            return jsonify(self.state_provider().get("positions", []))

        @self.app.get("/trades")
        def trades():
            return jsonify(self.state_provider().get("trades", []))

        @self.app.get("/signals")
        def signals():
            return jsonify(self.state_provider().get("signals", []))

        @self.app.get("/equity")
        def equity():
            return jsonify(self.state_provider().get("equity", []))

        @self.app.get("/")
        def index():
            return """
            <html><body>
            <h1>Trading Dashboard</h1>
            <pre id="data"></pre>
            <script>
            async function refresh() {
                const endpoints = ["health", "metrics", "positions", "trades", "signals", "equity"];
                const data = {};
                for (const endpoint of endpoints) {
                    const response = await fetch("/" + endpoint);
                    data[endpoint] = await response.json();
                }
                document.getElementById("data").textContent = JSON.stringify(data, null, 2);
            }
            refresh();
            setInterval(refresh, 5000);
            </script>
            </body></html>
            """

    def start(self) -> None:
        self._thread = threading.Thread(target=self.app.run, kwargs={"host": "0.0.0.0", "port": self.port, "use_reloader": False}, daemon=True)
        self._thread.start()
