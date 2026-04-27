"""LinkedIn job discovery — parses public LinkedIn job search results for ATS URLs.

Works best with a ``li_at`` session cookie (set ``LI_AT_COOKIE`` env var).
Without a cookie, LinkedIn's guest search may still surface some results but
will be rate-limited quickly.
"""

from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx

from .base import SlugCandidate

log = logging.getLogger(__name__)

_LI_JOBS_GUEST = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_LI_JOBS_SEARCH = "https://www.linkedin.com/jobs/search/"

_ATS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:job-boards|boards)\.greenhouse\.io/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I)),
]

# Searches chosen to surface jobs that have ATS-specific redirect URLs in HTML
_KEYWORD_MAP: list[tuple[str, str]] = [
    ("greenhouse", "greenhouse.io engineer"),
    ("lever", "lever.co engineer"),
    ("ashby", "ashbyhq engineer"),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_from_html(html: str, source: str) -> list[SlugCandidate]:
    results: list[SlugCandidate] = []
    seen: set[tuple[str, str]] = set()
    for ats, pat in _ATS_PATTERNS:
        for m in pat.finditer(html):
            slug = m.group(1).lower().split("/")[0]
            if (ats, slug) not in seen:
                seen.add((ats, slug))
                results.append(SlugCandidate(
                    slug=slug,
                    company=slug.replace("-", " ").title(),
                    ats=ats,
                    source=source,
                ))
    return results


class LinkedInSource:
    """Discover ATS board slugs from LinkedIn public job search."""

    name = "linkedin"

    def __init__(self, li_at_cookie: str = "") -> None:
        self.li_at_cookie = li_at_cookie

    def iter_candidates(self) -> Iterator[SlugCandidate]:
        headers = dict(_HEADERS)
        if self.li_at_cookie:
            headers["Cookie"] = f"li_at={self.li_at_cookie}"

        seen: set[tuple[str, str]] = set()
        with httpx.Client(
            timeout=30.0, headers=headers, follow_redirects=True
        ) as client:
            for _ats_hint, keywords in _KEYWORD_MAP:
                for start in range(0, 50, 25):  # two pages max per query
                    try:
                        r = client.get(
                            _LI_JOBS_GUEST,
                            params={
                                "keywords": keywords,
                                "location": "United States",
                                "start": str(start),
                            },
                        )
                    except (httpx.HTTPError, OSError) as e:
                        log.warning("LinkedInSource request failed: %s", e)
                        break
                    if r.status_code in (401, 403, 429):
                        log.warning(
                            "LinkedInSource: HTTP %d for %r — "
                            "set LI_AT_COOKIE for authenticated access",
                            r.status_code, keywords,
                        )
                        break
                    if not r.is_success:
                        log.warning("LinkedInSource: HTTP %d for %r", r.status_code, keywords)
                        break
                    for c in _extract_from_html(r.text, self.name):
                        key = (c.ats, c.slug)
                        if key not in seen:
                            seen.add(key)
                            yield c
        log.info("LinkedInSource: %d unique slugs found", len(seen))
