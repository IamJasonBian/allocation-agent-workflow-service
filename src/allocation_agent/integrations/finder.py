"""HTTP client to **finder-mock** (or a compatible crawler read service).

**Integration map (prod-like)**

1. Run finder-mock (same default port as ``crawler_base_url``): it applies ``robots.txt`` on
   ``POST /v1/seed`` and exposes ``GET /v1/jobs`` for the agent.
2. Seed URLs: ``seed_finder_url`` / ``allocation-agent finder seed`` (one URL at a time is
   easiest to reason about for robots policy).
3. In **allocation-agent**, set env so ``CrawlerSource`` can read the same base URL:
   ``CRAWLER_USE_HTTP=1``, ``CRAWLER_BASE_URL=http://127.0.0.1:8765`` (or the port you bound),
   and add ``"crawler"`` to ``ENABLED_SOURCES`` (JSON list in env, e.g.
   ``'["dover","crawler"]'``).
4. ``load_candidates()`` merges Dover + HTTP crawler like any other source; the selector/apply
   pipeline is unchanged. Use ``APPLY_MODE=mock`` for safe dry-runs; ``node`` is real browser.

5. **Preflight** before a batch: ``finder_reachable()`` (``GET /health``).

`CrawlerSource` (see ``sources/crawler``) is the read path; this module is the **write** path
(plus status/jobs JSON helpers for ops).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings


def _base() -> str:
    return str(settings.crawler_base_url).rstrip("/")


def finder_reachable() -> bool:
    """True if ``GET {crawler_base_url}/health`` returns 2xx (finder-mock is up)."""
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(f"{_base()}/health")
        return r.is_success
    except (httpx.HTTPError, OSError):
        return False


def seed_finder_url(url: str, depth: int = 0) -> dict[str, Any]:
    """POST /v1/seed — enqueue one URL (403 if robots forbid)."""
    with httpx.Client(timeout=10.0) as client:
        r = client.post(
            f"{_base()}/v1/seed",
            json={"url": url, "depth": depth},
        )
    r.raise_for_status()
    return r.json()


def seed_finder_batch(urls: list[str], depth: int = 0) -> list[dict[str, Any]]:
    """POST /v1/seed/batch (first disallowed URL aborts with 403)."""
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{_base()}/v1/seed/batch",
            json={"urls": urls, "depth": depth},
        )
    r.raise_for_status()
    return r.json()


def finder_status() -> dict[str, Any]:
    """GET /v1/status — pool depth, processed counts, etc."""
    with httpx.Client(timeout=5.0) as client:
        r = client.get(f"{_base()}/v1/status")
        r.raise_for_status()
        return r.json()


def finder_jobs_json(limit: int = 100) -> dict[str, Any]:
    """GET /v1/jobs — same JSON ``CrawlerSource`` consumes in HTTP mode."""
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{_base()}/v1/jobs", params={"limit": limit})
        r.raise_for_status()
        return r.json()
