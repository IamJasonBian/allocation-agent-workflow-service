"""Minimal operator dashboard for the worker pipeline."""

from __future__ import annotations

import os
import time
from typing import Any

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from ..config import settings
from ..stores.feedback import recent_outcomes

QUEUE_NAMES = ("select", "apply", "feedback")
INSPECT_CACHE_TTL = 2.0

app = FastAPI(title="allocation-agent dashboard", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("DASHBOARD_CORS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_redis_client: redis.Redis | None = None
_inspect_cache: dict[str, Any] = {"ts": 0.0, "value": None}


def _redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, socket_timeout=1.0)
    return _redis_client


@app.get("/api/health")
def health() -> dict:
    redis_ok = False
    try:
        redis_ok = bool(_redis().ping())
    except Exception:
        redis_ok = False
    return {"ok": True, "redis": redis_ok, "apply_mode": settings.apply_mode}


@app.get("/api/queues")
def api_queues() -> dict:
    """Live queue depth via Redis LLEN. Returns {select: 12, apply: 0, ...}."""
    depths: dict[str, int | None] = {}
    try:
        r = _redis()
        for q in QUEUE_NAMES:
            depths[q] = int(r.llen(q))
    except Exception:
        depths = {q: None for q in QUEUE_NAMES}
    return {"queues": depths}


@app.get("/api/workers")
def api_workers() -> dict:
    """Worker heartbeat + active task counts via Celery `inspect()` (cached 2s).

    Returns:
        {"workers": {"<hostname>": {"active": 3, "registered_tasks": 12}}, "stale": false}
    """
    now = time.monotonic()
    if _inspect_cache["value"] is not None and now - _inspect_cache["ts"] < INSPECT_CACHE_TTL:
        return {**_inspect_cache["value"], "stale": False}

    from ..celery_app import app as celery_app  # late import: avoid circular at module load

    workers: dict[str, dict[str, int]] = {}
    try:
        insp = celery_app.control.inspect(timeout=1.0)
        active = insp.active() or {}
        registered = insp.registered() or {}
        for host in set(active) | set(registered):
            workers[host] = {
                "active": len(active.get(host, [])),
                "registered_tasks": len(registered.get(host, [])),
            }
    except Exception:
        workers = {}

    payload = {"workers": workers}
    _inspect_cache["ts"] = now
    _inspect_cache["value"] = payload
    return {**payload, "stale": False}


@app.get("/api/outcomes")
def api_outcomes(limit: int = 50) -> list:
    return recent_outcomes(limit)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>allocation-agent</title>
  <style>
    :root { font-family: system-ui, sans-serif; background: #0f1419; color: #e6edf3; }
    body { max-width: 960px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-weight: 600; }
    h2 { font-size: 0.95rem; color: #8b949e; font-weight: 500; margin: 1.5rem 0 0.5rem; text-transform: uppercase; letter-spacing: 0.05em; }
    #status { margin: 1rem 0; padding: 0.75rem 1rem; background: #161b22; border-radius: 8px; }
    .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem; }
    .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 0.75rem 1rem; }
    .card .label { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; }
    .card .value { font-size: 1.6rem; font-weight: 600; margin-top: 0.25rem; }
    .card .value.dim { color: #6e7681; }
    .card .hot { color: #d29922; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { text-align: left; padding: 0.5rem 0.4rem; border-bottom: 1px solid #30363d; }
    th { color: #8b949e; font-weight: 500; }
    .pill { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; font-size: 0.75rem; }
    .submitted { background: #23863633; color: #3fb950; }
    .error { background: #f8514933; color: #f85149; }
    .captcha { background: #d2992233; color: #d29922; }
    code { background: #161b22; padding: 0.1rem 0.35rem; border-radius: 4px; }
    .muted { color: #6e7681; font-size: 0.75rem; }
    a { color: #58a6ff; }
  </style>
</head>
<body>
  <h1>allocation-agent</h1>
  <p>Operator dashboard — queue depth, worker health, recent outcomes.
     Deep-dive: <a href="http://localhost:5555" target="_blank">Flower</a> ·
     <a href="/docs">Swagger</a></p>
  <div id="status">Loading…</div>

  <h2>Queues</h2>
  <div id="queues" class="grid"></div>

  <h2>Workers</h2>
  <div id="workers" class="grid"></div>

  <h2>Recent outcomes</h2>
  <p id="rollup" style="color:#8b949e;font-size:0.9rem"></p>
  <table>
    <thead><tr><th>Candidate</th><th>Job</th><th>ATS</th><th>Status</th><th>Finished</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <p id="fetched" class="muted"></p>

  <script>
    async function jget(u) { const r = await fetch(u); if (!r.ok) throw new Error(u); return r.json(); }

    function renderQueues(data) {
      const el = document.getElementById('queues');
      el.innerHTML = Object.entries(data.queues).map(([name, depth]) => {
        const display = depth === null ? '—' : depth;
        const cls = depth === null ? 'dim' : (depth > 50 ? 'hot' : '');
        return `<div class="card"><div class="label">${name}</div><div class="value ${cls}">${display}</div></div>`;
      }).join('');
    }

    function renderWorkers(data) {
      const el = document.getElementById('workers');
      const hosts = Object.entries(data.workers);
      if (!hosts.length) {
        el.innerHTML = '<div class="card"><div class="label">No workers responding</div><div class="value dim">0</div></div>';
        return;
      }
      el.innerHTML = hosts.map(([host, w]) =>
        `<div class="card"><div class="label">${host}</div>
         <div class="value">${w.active}<span class="muted" style="font-size:0.8rem;font-weight:400"> active</span></div>
         <div class="muted">${w.registered_tasks} tasks registered</div></div>`
      ).join('');
    }

    function renderOutcomes(rows) {
      const tb = document.getElementById('rows');
      const counts = rows.reduce((acc, o) => { acc[o.status] = (acc[o.status] || 0) + 1; return acc; }, {});
      const parts = Object.keys(counts).sort().map(k => k + ': ' + counts[k]);
      document.getElementById('rollup').textContent =
        rows.length ? ('Batch summary — ' + parts.join(' · ')) : 'No outcomes yet.';
      tb.innerHTML = rows.map(o => {
        const cls = o.status === 'submitted' ? 'submitted'
          : o.status === 'captcha' ? 'captcha' : 'error';
        return `<tr><td>${o.candidate_id}</td><td>${o.job_id}</td><td>${o.ats}</td>` +
               `<td><span class="pill ${cls}">${o.status}</span></td><td>${o.finished_at || ''}</td></tr>`;
      }).join('');
    }

    async function load() {
      try {
        const [h, q, w, rows] = await Promise.all([
          jget('/api/health'),
          jget('/api/queues'),
          jget('/api/workers'),
          jget('/api/outcomes?limit=30'),
        ]);
        document.getElementById('status').innerHTML =
          'Health: ' + (h.ok ? 'ok' : 'degraded') +
          ' · Redis: ' + (h.redis ? 'up' : 'down') +
          ' · Apply mode: <code>' + h.apply_mode + '</code>';
        renderQueues(q);
        renderWorkers(w);
        renderOutcomes(rows);
        document.getElementById('fetched').textContent =
          'Last refresh: ' + new Date().toLocaleString();
      } catch (e) {
        document.getElementById('status').textContent = 'Failed to load: ' + e.message;
      }
    }
    load();
    setInterval(load, 5000);
  </script>
</body>
</html>
"""
