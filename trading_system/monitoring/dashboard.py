from __future__ import annotations

import threading
import time
from typing import Callable

from flask import Flask, jsonify, render_template_string


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Trading Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; }
    header { background: #161b22; padding: 16px 24px; border-bottom: 1px solid #30363d; display: flex; align-items: center; gap: 12px; }
    header h1 { font-size: 1.25rem; font-weight: 600; }
    .badge { font-size: 0.7rem; background: #238636; color: #fff; padding: 2px 8px; border-radius: 12px; }
    .badge.halted { background: #da3633; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; padding: 16px 24px; }
    .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
    .card h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; color: #8b949e; margin-bottom: 8px; }
    .metric { font-size: 1.6rem; font-weight: 700; color: #58a6ff; }
    .metric.green { color: #3fb950; }
    .metric.red { color: #f85149; }
    .section { padding: 0 24px 24px; }
    .section h2 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.06em; color: #8b949e; margin-bottom: 8px; border-bottom: 1px solid #30363d; padding-bottom: 6px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    th { text-align: left; padding: 6px 8px; color: #8b949e; border-bottom: 1px solid #21262d; }
    td { padding: 6px 8px; border-bottom: 1px solid #21262d; }
    tr:last-child td { border-bottom: none; }
    .pos { color: #3fb950; } .neg { color: #f85149; } .neu { color: #8b949e; }
    #equity-chart { width: 100%; height: 160px; }
    .sentiment-bar { height: 8px; background: #21262d; border-radius: 4px; overflow: hidden; margin-top: 4px; }
    .sentiment-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
    .refresh-ts { font-size: 0.7rem; color: #484f58; margin-left: auto; }
    .sector-grid { display: flex; flex-wrap: wrap; gap: 8px; }
    .sector-pill { background: #21262d; border-radius: 16px; padding: 4px 12px; font-size: 0.75rem; }
  </style>
</head>
<body>
  <header>
    <h1>⚡ Trading Dashboard</h1>
    <span class="badge" id="status-badge">LIVE</span>
    <span class="refresh-ts" id="refresh-ts"></span>
  </header>

  <!-- KPI cards -->
  <div class="grid" id="kpi-grid">
    <div class="card"><h2>Equity</h2><div class="metric" id="kpi-equity">—</div></div>
    <div class="card"><h2>Cash</h2><div class="metric" id="kpi-cash">—</div></div>
    <div class="card"><h2>Daily P&L</h2><div class="metric" id="kpi-pnl">—</div></div>
    <div class="card"><h2>Drawdown</h2><div class="metric" id="kpi-dd">—</div></div>
    <div class="card"><h2>Win Rate</h2><div class="metric" id="kpi-wr">—</div></div>
    <div class="card"><h2>Positions</h2><div class="metric" id="kpi-pos">—</div></div>
  </div>

  <!-- Equity chart -->
  <div class="section">
    <h2>Equity Curve</h2>
    <canvas id="equity-chart"></canvas>
  </div>

  <!-- Positions -->
  <div class="section">
    <h2>Open Positions</h2>
    <table id="positions-table">
      <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Last</th><th>Unrealised P&L</th><th>Strategy</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Sentiment -->
  <div class="section">
    <h2>Sentiment Scores</h2>
    <div id="sentiment-container" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px;"></div>
  </div>

  <!-- Universe -->
  <div class="section">
    <h2>Active Universe (<span id="universe-count">—</span> symbols)</h2>
    <div class="sector-grid" id="universe-pills"></div>
  </div>

  <!-- Signals -->
  <div class="section">
    <h2>Recent Signals</h2>
    <table id="signals-table">
      <thead><tr><th>Time</th><th>Symbol</th><th>Direction</th><th>Strength</th><th>Strategy</th><th>Reason</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Trades -->
  <div class="section">
    <h2>Recent Trades</h2>
    <table id="trades-table">
      <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Strategy</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Risk -->
  <div class="section">
    <h2>Risk / Sector Exposure</h2>
    <table id="risk-table">
      <thead><tr><th>Sector</th><th>Exposure</th><th>Limit</th><th>Status</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Performance -->
  <div class="section">
    <h2>Performance Summary</h2>
    <table id="perf-table">
      <thead><tr><th>Metric</th><th>Value</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

<script>
const fmt = (v, dec=2) => v == null ? '—' : Number(v).toLocaleString(undefined, {minimumFractionDigits:dec, maximumFractionDigits:dec});
const fmtPct = v => v == null ? '—' : (Number(v) >= 0 ? '+' : '') + fmt(v) + '%';
const fmtCur = v => v == null ? '—' : '$' + fmt(v);
const cls = v => v > 0 ? 'pos' : v < 0 ? 'neg' : 'neu';
const ts = s => s ? new Date(s).toLocaleTimeString() : '—';

let equityHistory = [];

function drawChart(canvas, data) {
  if (!data.length) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.offsetWidth;
  const h = canvas.height = 160;
  ctx.clearRect(0, 0, w, h);
  const vals = data.map(d => d.equity);
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = max - min || 1;
  const pad = 20;
  const scaleY = v => h - pad - ((v - min) / range) * (h - 2 * pad);
  const scaleX = i => pad + (i / (data.length - 1)) * (w - 2 * pad);
  ctx.strokeStyle = '#58a6ff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  data.forEach((d, i) => { i === 0 ? ctx.moveTo(scaleX(i), scaleY(d.equity)) : ctx.lineTo(scaleX(i), scaleY(d.equity)); });
  ctx.stroke();
  // Fill
  ctx.lineTo(scaleX(data.length - 1), h - pad);
  ctx.lineTo(scaleX(0), h - pad);
  ctx.closePath();
  ctx.fillStyle = 'rgba(88,166,255,0.08)';
  ctx.fill();
}

function renderPositions(positions) {
  const tbody = document.querySelector('#positions-table tbody');
  tbody.innerHTML = '';
  if (!positions.length) { tbody.innerHTML = '<tr><td colspan="7" class="neu" style="text-align:center;padding:16px">No open positions</td></tr>'; return; }
  positions.forEach(p => {
    const pnl = p.unrealised_pnl;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${p.symbol}</td><td class="${p.side==='long'?'pos':'neg'}">${p.side}</td><td>${fmt(p.qty,0)}</td><td>${fmtCur(p.entry_price)}</td><td>${fmtCur(p.last_price||p.entry_price)}</td><td class="${cls(pnl)}">${fmtCur(pnl)}</td><td>${p.strategy||'—'}</td>`;
    tbody.appendChild(tr);
  });
}

function renderSignals(signals) {
  const tbody = document.querySelector('#signals-table tbody');
  tbody.innerHTML = '';
  const recent = [...signals].reverse().slice(0, 20);
  recent.forEach(s => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${ts(s.timestamp)}</td><td>${s.symbol}</td><td class="${s.direction==='long'?'pos':s.direction==='short'?'neg':'neu'}">${s.direction}</td><td>${fmt(s.strength,2)}</td><td>${s.strategy}</td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.reason||''}</td>`;
    tbody.appendChild(tr);
  });
}

function renderTrades(trades) {
  const tbody = document.querySelector('#trades-table tbody');
  tbody.innerHTML = '';
  const recent = [...trades].reverse().slice(0, 20);
  recent.forEach(t => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${t.symbol}</td><td class="${t.side==='long'?'pos':'neg'}">${t.side}</td><td>${fmt(t.qty,0)}</td><td>${fmtCur(t.entry_price)}</td><td>${fmtCur(t.exit_price)}</td><td class="${cls(t.pnl)}">${fmtCur(t.pnl)}</td><td>${t.strategy||'—'}</td>`;
    tbody.appendChild(tr);
  });
}

function renderSentiment(sentiment) {
  const container = document.getElementById('sentiment-container');
  container.innerHTML = '';
  Object.entries(sentiment).forEach(([sym, s]) => {
    const score = s.score ?? 0;
    const pct = Math.round((score + 1) / 2 * 100);
    const colour = score > 0.1 ? '#3fb950' : score < -0.1 ? '#f85149' : '#e3b341';
    container.innerHTML += `
      <div class="card" style="padding:10px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <strong>${sym}</strong><span style="color:${colour}">${fmt(score,3)}</span>
        </div>
        <div class="sentiment-bar"><div class="sentiment-fill" style="width:${pct}%;background:${colour}"></div></div>
        <div style="font-size:0.7rem;color:#8b949e;margin-top:4px">
          N:${fmt(s.news_score,2)} T:${fmt(s.technical_score,2)} R:${fmt(s.regime_score,2)} V:${fmt(s.vix_score,2)}
        </div>
      </div>`;
  });
}

function renderUniverse(symbols) {
  document.getElementById('universe-count').textContent = symbols.length;
  const container = document.getElementById('universe-pills');
  container.innerHTML = symbols.map(s => `<span class="sector-pill">${s}</span>`).join('');
}

function renderRisk(risk) {
  const tbody = document.querySelector('#risk-table tbody');
  tbody.innerHTML = '';
  const exposures = risk.sector_exposures || {};
  const limit = risk.max_sector_pct || 0.20;
  Object.entries(exposures).forEach(([sector, pct]) => {
    const over = pct > limit;
    tbody.innerHTML += `<tr><td>${sector}</td><td>${fmtPct(pct*100)}</td><td>${fmtPct(limit*100)}</td><td class="${over?'neg':'pos'}">${over?'⚠ OVER LIMIT':'✓ OK'}</td></tr>`;
  });
  if (!Object.keys(exposures).length) tbody.innerHTML = '<tr><td colspan="4" class="neu" style="text-align:center;padding:12px">No positions</td></tr>';
}

function renderPerformance(perf) {
  const tbody = document.querySelector('#perf-table tbody');
  tbody.innerHTML = '';
  const rows = [
    ['Total Trades', perf.total_trades],
    ['Win Rate', fmtPct(perf.win_rate)],
    ['Profit Factor', fmt(perf.profit_factor)],
    ['Avg Win', fmtCur(perf.avg_win)],
    ['Avg Loss', fmtCur(perf.avg_loss)],
    ['Sharpe (approx)', fmt(perf.sharpe)],
    ['Max Drawdown', fmtPct(perf.max_drawdown_pct)],
    ['Total P&L', fmtCur(perf.total_pnl)],
  ];
  rows.forEach(([k, v]) => { tbody.innerHTML += `<tr><td>${k}</td><td>${v??'—'}</td></tr>`; });
}

async function refresh() {
  try {
    const [metrics, positions, signals, trades, equity, sentiment, universe, risk, perf] = await Promise.all([
      fetch('/metrics').then(r=>r.json()),
      fetch('/positions').then(r=>r.json()),
      fetch('/signals').then(r=>r.json()),
      fetch('/trades').then(r=>r.json()),
      fetch('/equity').then(r=>r.json()),
      fetch('/sentiment').then(r=>r.json()).catch(()=>({})),
      fetch('/universe').then(r=>r.json()).catch(()=>[]),
      fetch('/risk').then(r=>r.json()).catch(()=>({})),
      fetch('/performance').then(r=>r.json()).catch(()=>({})),
    ]);

    // KPI
    const pnl = metrics.daily_pnl;
    document.getElementById('kpi-equity').textContent = fmtCur(metrics.equity);
    document.getElementById('kpi-cash').textContent = fmtCur(metrics.cash);
    document.getElementById('kpi-pnl').className = 'metric ' + cls(pnl);
    document.getElementById('kpi-pnl').textContent = fmtCur(pnl);
    document.getElementById('kpi-dd').className = 'metric ' + (metrics.drawdown_pct > 5 ? 'red' : 'green');
    document.getElementById('kpi-dd').textContent = fmtPct(metrics.drawdown_pct);
    document.getElementById('kpi-wr').textContent = fmtPct(metrics.win_rate);
    document.getElementById('kpi-pos').textContent = metrics.positions ?? '—';

    const badge = document.getElementById('status-badge');
    if (metrics.circuit_breaker) { badge.textContent = 'HALTED'; badge.className = 'badge halted'; }
    else { badge.textContent = 'LIVE'; badge.className = 'badge'; }

    // Chart
    equityHistory = equity.slice(-200);
    drawChart(document.getElementById('equity-chart'), equityHistory);

    renderPositions(positions);
    renderSignals(signals);
    renderTrades(trades);
    renderSentiment(sentiment);
    renderUniverse(Array.isArray(universe) ? universe : (universe.symbols || []));
    renderRisk(risk);
    renderPerformance(perf);

    document.getElementById('refresh-ts').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) { console.error('Dashboard refresh error', e); }
}

refresh();
setInterval(refresh, 5000);
window.addEventListener('resize', () => drawChart(document.getElementById('equity-chart'), equityHistory));
</script>
</body>
</html>
"""


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

        @self.app.get("/sentiment")
        def sentiment():
            return jsonify(self.state_provider().get("sentiment", {}))

        @self.app.get("/universe")
        def universe():
            return jsonify(self.state_provider().get("universe", []))

        @self.app.get("/signals/history")
        def signals_history():
            return jsonify(self.state_provider().get("signals_history", []))

        @self.app.get("/performance")
        def performance():
            return jsonify(self.state_provider().get("performance", {}))

        @self.app.get("/risk")
        def risk():
            return jsonify(self.state_provider().get("risk", {}))

        @self.app.get("/")
        def index():
            return render_template_string(_HTML_TEMPLATE)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.app.run,
            kwargs={"host": "0.0.0.0", "port": self.port, "use_reloader": False},
            daemon=True,
        )
        self._thread.start()
