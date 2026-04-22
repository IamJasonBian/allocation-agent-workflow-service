"""Ops helpers for the **Allocation Crawler** HTTP API (Netlify).

OpenAPI is served at
https://allocation-crawler-service.netlify.app/api/crawler/docs

This is a different contract than ``finder-mock`` (``/v1/jobs``); the agent maps
``GET /api/crawler/jobs`` rows in :mod:`allocation_agent.sources.crawler` when
``crawler_http_backend=allocation_crawler``.
"""

from __future__ import annotations

from typing import Any

import httpx


def list_boards(api_base: str, timeout_s: float = 30.0) -> dict[str, Any]:
    """GET ``{api_base}/boards`` — returns ``count`` and ``boards`` list."""
    b = api_base.rstrip("/")
    with httpx.Client(timeout=timeout_s) as client:
        r = client.get(f"{b}/boards")
        r.raise_for_status()
        return r.json()


def greenhouse_board_frontier_url(board_id: str) -> str:
    """Typical public Greenhouse **job board** (listings) URL for a board slug.

    (Individual job URLs in the API are company-specific, e.g. ``coinbase.com/careers/...``.)
    """
    slug = (board_id or "").strip()
    return f"https://job-boards.greenhouse.io/{slug}"
