"""Google search discovery via SerpAPI (requires SERPAPI_KEY env var).

Searches for ``site:job-boards.greenhouse.io``, ``site:jobs.lever.co``, and
``site:jobs.ashbyhq.com`` to surface new company slugs.
"""

from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx

from .base import SlugCandidate

log = logging.getLogger(__name__)

_SERPAPI = "https://serpapi.com/search"

_QUERIES: list[tuple[str, str]] = [
    ("greenhouse", "site:job-boards.greenhouse.io"),
    ("greenhouse", "site:boards.greenhouse.io"),
    ("lever", "site:jobs.lever.co"),
    ("ashby", "site:jobs.ashbyhq.com"),
]

_SLUG_PAT: dict[str, re.Pattern] = {
    "greenhouse": re.compile(r"(?:job-boards|boards)\.greenhouse\.io/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I),
    "lever": re.compile(r"jobs\.lever\.co/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I),
}


def _slug_from_url(ats: str, url: str) -> str | None:
    m = _SLUG_PAT[ats].search(url)
    return m.group(1).lower().split("/")[0] if m else None


class GoogleSearchSource:
    """Discover ATS board slugs via SerpAPI Google search."""

    name = "google_search"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    def iter_candidates(self) -> Iterator[SlugCandidate]:
        if not self.api_key:
            log.debug("GoogleSearchSource: SERPAPI_KEY not configured, skipping")
            return
        seen: set[tuple[str, str]] = set()
        with httpx.Client(timeout=30.0) as client:
            for ats, query in _QUERIES:
                try:
                    r = client.get(_SERPAPI, params={
                        "engine": "google",
                        "q": query,
                        "api_key": self.api_key,
                        "num": 100,
                    })
                    r.raise_for_status()
                    data = r.json()
                except (httpx.HTTPError, OSError, ValueError) as e:
                    log.warning("GoogleSearchSource %r failed: %s", query, e)
                    continue
                for result in data.get("organic_results", []):
                    slug = _slug_from_url(ats, result.get("link", ""))
                    if slug and (ats, slug) not in seen:
                        seen.add((ats, slug))
                        yield SlugCandidate(
                            slug=slug,
                            company=slug.replace("-", " ").title(),
                            ats=ats,
                            source=self.name,
                        )
        log.info("GoogleSearchSource: %d unique slugs found", len(seen))
