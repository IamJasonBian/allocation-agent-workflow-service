"""Daily Celery task: discover new board slugs and seed them into the crawler service.

Run schedule: 02:00 UTC daily (configured in ``celery_app.py`` beat schedule).

The task:
1. Fetches existing board IDs from the crawler API to avoid re-seeding.
2. Runs all enabled slug discovery strategies (HN posts, Google search,
   LinkedIn, ATS sitemaps, etc.) to surface new ``(ats, slug)`` pairs.
3. Filters to only previously-unknown slugs.
4. POSTs each new slug to ``POST /api/crawler/boards``.
5. Returns a summary dict logged at INFO level.

Run ad-hoc::

    allocation-agent crawler discover [--dry-run]
"""

from __future__ import annotations

import logging
from datetime import date, timezone, datetime
from typing import Any

import httpx

from ..celery_app import app
from ..config import settings
from ..integrations.allocation_crawler import get_existing_board_ids, seed_board
from ..integrations.slug_sources import load_slug_candidates

log = logging.getLogger(__name__)


def _run_discovery(
    dry_run: bool = False,
    api_base: str | None = None,
    enabled_strategies: list[str] | None = None,
) -> dict[str, Any]:
    """Core discovery logic (callable directly from CLI or Celery task)."""
    run_date = date.today().isoformat()
    api_base = (api_base or settings.discovery_api_base).rstrip("/")
    strategies = enabled_strategies or settings.discovery_enabled_strategies

    log.info(
        "slug_discovery: run_date=%s dry_run=%s strategies=%s api_base=%s",
        run_date, dry_run, strategies, api_base,
    )

    errors: list[str] = []
    new_boards: list[dict] = []

    # 1 — existing boards
    try:
        existing_ids = get_existing_board_ids(api_base)
        log.info("slug_discovery: %d boards already in crawler", len(existing_ids))
    except Exception as exc:
        log.error("slug_discovery: failed to fetch existing boards: %s", exc)
        errors.append(f"fetch_existing:{exc}")
        existing_ids = set()

    # 2 — discovery
    try:
        candidates = load_slug_candidates(
            enabled_strategies=strategies,
            serpapi_key=settings.serpapi_key,
            li_at_cookie=settings.li_at_cookie,
            include_yc=settings.discovery_include_yc,
        )
        log.info("slug_discovery: %d candidates surfaced", len(candidates))
    except Exception as exc:
        log.error("slug_discovery: discovery phase error: %s", exc)
        errors.append(f"discovery:{exc}")
        candidates = []

    # 3 — filter
    new_candidates = [c for c in candidates if c.slug not in existing_ids]
    already_known = len(candidates) - len(new_candidates)
    log.info(
        "slug_discovery: %d new, %d already known",
        len(new_candidates), already_known,
    )

    # 4 — seed
    seeded = 0
    for c in new_candidates:
        entry = {
            "id": c.slug,
            "company": c.company,
            "ats": c.ats,
            "source": c.source,
            "career_page_url": c.career_page_url,
        }
        if dry_run:
            log.info("slug_discovery [dry_run]: would seed %s/%s (from %s)", c.ats, c.slug, c.source)
            new_boards.append(entry)
            seeded += 1
            continue
        try:
            seed_board(
                api_base=api_base,
                board_id=c.slug,
                company=c.company,
                ats=c.ats,
                career_page_url=c.career_page_url,
                api_key=settings.alloc_crawler_api_key,
            )
            new_boards.append(entry)
            seeded += 1
            log.info("slug_discovery: seeded %s/%s (from %s)", c.ats, c.slug, c.source)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                # Already exists — race with another process or stale local cache
                log.debug("slug_discovery: %s already exists (409), skipping", c.slug)
            else:
                log.warning("slug_discovery: seed %s failed HTTP %d: %s", c.slug, exc.response.status_code, exc)
                errors.append(f"seed:{c.slug}:HTTP{exc.response.status_code}")
        except Exception as exc:
            log.warning("slug_discovery: seed %s failed: %s", c.slug, exc)
            errors.append(f"seed:{c.slug}:{exc}")

    summary: dict[str, Any] = {
        "run_date": run_date,
        "strategies_run": strategies,
        "candidates_found": len(candidates),
        "already_known": already_known,
        "newly_seeded": seeded,
        "new_boards": new_boards,
        "errors": errors,
        "dry_run": dry_run,
    }
    log.info("slug_discovery: summary=%s", summary)
    return summary


@app.task(
    bind=True,
    name="allocation_agent.tasks.slug_discovery.discover_and_seed_boards",
    max_retries=2,
    default_retry_delay=120,
    soft_time_limit=1800,
    time_limit=1860,
    queue="select",
)
def discover_and_seed_boards(self, dry_run: bool = False) -> dict[str, Any]:
    """Daily Celery task: discover new board slugs and seed them into the crawler.

    Returns a summary dict with counts and the list of newly seeded boards.
    """
    try:
        return _run_discovery(dry_run=dry_run)
    except Exception as exc:
        log.error("slug_discovery: unhandled error: %s", exc, exc_info=True)
        raise self.retry(exc=exc)
