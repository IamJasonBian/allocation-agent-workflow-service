"""HTTP client for the local finder-mock service (`gamma/finder-mock`).

Set `crawler_base_url` in settings to the same base URL the service listens on
(default `http://127.0.0.1:8765`). Seed URLs here; `CrawlerSource` with
`crawler_use_http=True` ingests completed jobs from GET /v1/jobs.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import settings


def _base() -> str:
    return str(settings.crawler_base_url).rstrip("/")


def seed_finder_url(url: str, depth: int = 0) -> dict[str, Any]:
    """POST /v1/seed — enqueue one URL for the worker pool (403 if robots forbid)."""
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
    """GET /v1/jobs — same payload `CrawlerSource` uses in HTTP mode."""
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{_base()}/v1/jobs", params={"limit": limit})
        r.raise_for_status()
        return r.json()


def print_finder_status() -> str:
    """One-line JSON for CLI."""
    return json.dumps(finder_status(), indent=2)
