"""Other slug discovery: ATS public sitemaps and YC company directory.

- **ATS sitemaps**: ``boards.greenhouse.io/sitemap.xml``, ``jobs.lever.co/sitemap.xml``,
  ``jobs.ashbyhq.com/sitemap.xml`` — each lists every active company board.
- **YC companies**: Algolia-backed search on ycombinator.com (public read-only key).
"""

from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx

from .base import SlugCandidate

log = logging.getLogger(__name__)

_SITEMAP_SOURCES: list[tuple[str, str, re.Pattern]] = [
    (
        "greenhouse",
        "https://boards.greenhouse.io/sitemap.xml",
        re.compile(r"boards\.greenhouse\.io/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I),
    ),
    (
        "greenhouse",
        "https://job-boards.greenhouse.io/sitemap.xml",
        re.compile(r"job-boards\.greenhouse\.io/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I),
    ),
    (
        "lever",
        "https://jobs.lever.co/sitemap.xml",
        re.compile(r"jobs\.lever\.co/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I),
    ),
    (
        "ashby",
        "https://jobs.ashbyhq.com/sitemap.xml",
        re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I),
    ),
]

# Public read-only Algolia key used by ycombinator.com company search
_YC_ALGOLIA_URL = "https://45bwzj1sgc-dsn.algolia.net/1/indexes/*/queries"
_YC_APP_ID = "45BWZJ1SGC"
_YC_API_KEY = "be96dfad27a7428f8b74ab51a34b4aef"


def _fetch_sitemap_slugs(
    client: httpx.Client, ats: str, url: str, pat: re.Pattern
) -> list[SlugCandidate]:
    try:
        r = client.get(url, timeout=60.0)
        r.raise_for_status()
    except (httpx.HTTPError, OSError) as e:
        log.warning("Sitemap fetch failed %s: %s", url, e)
        return []
    results: list[SlugCandidate] = []
    seen: set[str] = set()
    for m in pat.finditer(r.text):
        slug = m.group(1).lower().split("/")[0]
        # Skip generic path segments like "jobs", "embed", "api"
        if slug in ("jobs", "embed", "api", "v1", "boards") or not slug:
            continue
        if slug not in seen:
            seen.add(slug)
            results.append(SlugCandidate(
                slug=slug,
                company=slug.replace("-", " ").title(),
                ats=ats,
                source="ats_sitemap",
            ))
    log.info("Sitemap %s → %d slugs", url, len(results))
    return results


def _fetch_yc_slugs(client: httpx.Client) -> list[SlugCandidate]:
    """Query YC Algolia for company names; return greenhouse slug guesses."""
    try:
        r = client.post(
            _YC_ALGOLIA_URL,
            headers={
                "X-Algolia-Application-Id": _YC_APP_ID,
                "X-Algolia-API-Key": _YC_API_KEY,
                "Content-Type": "application/json",
            },
            json={"requests": [{"indexName": "companies", "params": "hitsPerPage=1000&page=0"}]},
            timeout=30.0,
        )
        r.raise_for_status()
        hits = r.json().get("results", [{}])[0].get("hits", [])
    except (httpx.HTTPError, OSError, ValueError) as e:
        log.warning("YC Algolia search failed: %s", e)
        return []

    results: list[SlugCandidate] = []
    seen: set[str] = set()
    for h in hits:
        name = (h.get("name") or "").strip()
        if not name:
            continue
        # Derive a plausible slug (no spaces, lowercase, strip punctuation)
        slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "").replace("_", ""))
        if slug and slug not in seen:
            seen.add(slug)
            results.append(SlugCandidate(
                slug=slug,
                company=name,
                ats="greenhouse",  # most common for YC cos; crawler will validate
                source="yc_companies",
                career_page_url=h.get("url") or "",
            ))
    log.info("YC Algolia → %d company slug guesses", len(results))
    return results


class OtherSource:
    """Discover slugs from ATS public sitemaps and optionally YC company directory."""

    name = "other"

    def __init__(self, include_yc: bool = False) -> None:
        self.include_yc = include_yc

    def iter_candidates(self) -> Iterator[SlugCandidate]:
        seen: set[tuple[str, str]] = set()
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            for ats, url, pat in _SITEMAP_SOURCES:
                for c in _fetch_sitemap_slugs(client, ats, url, pat):
                    key = (c.ats, c.slug)
                    if key not in seen:
                        seen.add(key)
                        yield c
            if self.include_yc:
                for c in _fetch_yc_slugs(client):
                    key = (c.ats, c.slug)
                    if key not in seen:
                        seen.add(key)
                        yield c
