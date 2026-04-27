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


def get_existing_board_ids(api_base: str, timeout_s: float = 30.0) -> set[str]:
    """Return the set of board ``id`` strings already registered in the crawler service."""
    data = list_boards(api_base, timeout_s=timeout_s)
    return {b.get("id", "") for b in (data.get("boards") or []) if b.get("id")}


def seed_board(
    api_base: str,
    board_id: str,
    company: str,
    ats: str,
    career_page_url: str = "",
    api_key: str = "",
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """POST ``{api_base}/boards`` — register one new board slug.

    Raises :class:`httpx.HTTPStatusError` on 4xx/5xx so callers can decide
    whether to skip (409 Conflict = already exists) or abort.
    """
    b = api_base.rstrip("/")
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with httpx.Client(timeout=timeout_s) as client:
        r = client.post(
            f"{b}/boards",
            json={
                "id": board_id,
                "company": company,
                "ats": ats,
                "career_page_url": career_page_url,
            },
            headers=headers,
        )
        r.raise_for_status()
        return r.json()


def greenhouse_board_frontier_url(board_id: str) -> str:
    """Typical public Greenhouse **job board** (listings) URL for a board slug.

    (Individual job URLs in the API are company-specific, e.g. ``coinbase.com/careers/...``.)
    """
    slug = (board_id or "").strip()
    return f"https://job-boards.greenhouse.io/{slug}"
