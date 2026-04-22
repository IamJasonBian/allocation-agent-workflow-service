"""Minimal operator dashboard for the worker pipeline."""

from __future__ import annotations

import os

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from ..config import settings
from ..stores.feedback import recent_outcomes

app = FastAPI(title="allocation-agent dashboard", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("DASHBOARD_CORS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    redis_ok = False
    try:
        r = redis.from_url(settings.redis_url)
        redis_ok = r.ping()
    except Exception:
        redis_ok = False
    return {"ok": True, "redis": redis_ok, "apply_mode": settings.apply_mode}


@app.get("/api/outcomes")
def api_outcomes(limit: int = 50) -> list:
    return recent_outcomes(limit)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>allocation-agent</title>
  <style>
    :root { font-family: system-ui, sans-serif; background: #0f1419; color: #e6edf3; }
    body { max-width: 960px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-weight: 600; }
    #status { margin: 1rem 0; padding: 0.75rem 1rem; background: #161b22; border-radius: 8px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { text-align: left; padding: 0.5rem 0.4rem; border-bottom: 1px solid #30363d; }
    th { color: #8b949e; font-weight: 500; }
    .pill { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; font-size: 0.75rem; }
    .submitted { background: #23863633; color: #3fb950; }
    .error { background: #f8514933; color: #f85149; }
    .captcha { background: #d2992233; color: #d29922; }
  </style>
</head>
<body>
  <h1>allocation-agent</h1>
  <p>NYC spray pipeline — recent apply outcomes (feedback store).</p>
  <div id="status">Loading…</div>
  <p id="rollup" style="color:#8b949e;font-size:0.9rem"></p>
  <p id="fetched" style="color:#6e7681;font-size:0.75rem"></p>
  <table>
    <thead><tr><th>Candidate</th><th>Job</th><th>ATS</th><th>Status</th><th>Finished</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <script>
    async function load() {
      const h = await fetch('/api/health').then(r => r.json());
      document.getElementById('status').innerHTML =
        'Health: ' + (h.ok ? 'ok' : 'degraded') +
        ' · Redis: ' + (h.redis ? 'up' : 'down') +
        ' · Apply mode: <code>' + h.apply_mode + '</code>';
      const rows = await fetch('/api/outcomes?limit=30').then(r => r.json());
      const tb = document.getElementById('rows');
      const counts = rows.reduce((acc, o) => {
        acc[o.status] = (acc[o.status] || 0) + 1;
        return acc;
      }, {});
      const parts = Object.keys(counts).sort().map(k => k + ': ' + counts[k]);
      document.getElementById('rollup').textContent =
        rows.length ? ('Batch summary — ' + parts.join(' · ')) : 'No outcomes yet.';
      document.getElementById('fetched').textContent =
        'Last refresh: ' + new Date().toLocaleString();
      tb.innerHTML = rows.map(o => {
        const cls = o.status === 'submitted' ? 'submitted'
          : o.status === 'captcha' ? 'captcha' : 'error';
        return '<tr><td>' + o.candidate_id + '</td><td>' + o.job_id +
          '</td><td>' + o.ats + '</td><td><span class="pill ' + cls + '">' + o.status +
          '</span></td><td>' + (o.finished_at || '') + '</td></tr>';
      }).join('');
    }
    load();
    setInterval(load, 15000);
  </script>
</body>
</html>
"""
