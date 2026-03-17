from __future__ import annotations

import json
from pathlib import Path

from trading_system.backtest.metrics import PerformanceMetrics
from trading_system.storage.models import Trade


class ReportGenerator:
    def __repr__(self) -> str:
        return "ReportGenerator()"

    def generate(self, output_path: Path, metrics: PerformanceMetrics, equity_curve: list[dict], trades: list[Trade]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_json = json.dumps(metrics.__dict__, indent=2, default=str)
        equity_json = json.dumps([{**point, "timestamp": point["timestamp"].isoformat()} for point in equity_curve], default=str)
        trades_json = json.dumps([trade.__dict__ for trade in trades], default=str)
        monthly_rows = "".join(
            f"<tr><td>{month}</td><td>{value:.2f}%</td></tr>" for month, value in metrics.monthly_returns.items()
        )
        html = f"""
        <html>
        <head>
            <title>Backtest Report</title>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        </head>
        <body>
            <h1>Backtest Report</h1>
            <h2>Summary</h2>
            <pre>{metrics_json}</pre>
            <h2>Equity Curve</h2>
            <canvas id="equityChart"></canvas>
            <h2>Monthly Returns</h2>
            <table border="1"><tr><th>Month</th><th>Return</th></tr>{monthly_rows}</table>
            <h2>Trade Log</h2>
            <pre>{trades_json}</pre>
            <script>
            const equityData = {equity_json};
            new Chart(document.getElementById('equityChart'), {{
                type: 'line',
                data: {{
                    labels: equityData.map(point => point.timestamp),
                    datasets: [{{ label: 'Equity', data: equityData.map(point => point.equity), borderColor: 'green' }}]
                }}
            }});
            </script>
        </body>
        </html>
        """
        output_path.write_text(html, encoding="utf-8")

