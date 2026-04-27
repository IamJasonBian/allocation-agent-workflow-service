"""HN 'Who is Hiring' post discovery — parses monthly hiring threads for ATS URLs."""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date
from typing import Iterator

import httpx

from .base import SlugCandidate

log = logging.getLogger(__name__)

_HN_ALGOLIA = "https://hn.algolia.com/api/v1/search"

_ATS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:job-boards|boards)\.greenhouse\.io/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I)),
]


def _extract_from_text(text: str, source: str) -> list[SlugCandidate]:
    results: list[SlugCandidate] = []
    seen: set[tuple[str, str]] = set()
    for ats, pat in _ATS_PATTERNS:
        for m in pat.finditer(text):
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


def _find_hiring_thread_id(client: httpx.Client, year: int, month: int) -> str | None:
    month_name = calendar.month_name[month]
    for query in [
        f"Ask HN: Who is hiring? ({month_name} {year})",
        f"Ask HN: Who is hiring? ({month_name}",
    ]:
        try:
            r = client.get(_HN_ALGOLIA, params={
                "query": query,
                "tags": "story",
                "hitsPerPage": 10,
            }, timeout=15.0)
            r.raise_for_status()
            for h in r.json().get("hits", []):
                title = h.get("title", "").lower()
                if "who is hiring" in title and str(year) in h.get("title", ""):
                    return h.get("objectID")
        except (httpx.HTTPError, OSError, ValueError) as e:
            log.warning("HN search failed for %r: %s", query, e)
    return None


def _iter_comments(client: httpx.Client, story_id: str) -> Iterator[str]:
    page = 0
    while True:
        try:
            r = client.get(_HN_ALGOLIA, params={
                "tags": f"comment,story_{story_id}",
                "hitsPerPage": 1000,
                "page": page,
            }, timeout=30.0)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, OSError, ValueError) as e:
            log.warning("HN comments page %d failed: %s", page, e)
            break
        hits = data.get("hits", [])
        if not hits:
            break
        for h in hits:
            text = h.get("comment_text") or ""
            if text:
                yield text
        page += 1
        if page >= data.get("nbPages", 1):
            break


class HNPostsSource:
    """Discover ATS board slugs from HN 'Who is Hiring' monthly threads."""

    name = "hn_posts"

    def __init__(self, year: int | None = None, month: int | None = None) -> None:
        today = date.today()
        self.year = year or today.year
        self.month = month or today.month

    def iter_candidates(self) -> Iterator[SlugCandidate]:
        with httpx.Client(timeout=30.0) as client:
            story_id = _find_hiring_thread_id(client, self.year, self.month)
            if not story_id:
                log.warning(
                    "HNPostsSource: no 'Who is Hiring' thread found for %d/%d",
                    self.month, self.year,
                )
                return
            log.info("HNPostsSource: found story %s, fetching comments", story_id)
            seen: set[tuple[str, str]] = set()
            count = 0
            for text in _iter_comments(client, story_id):
                count += 1
                for c in _extract_from_text(text, self.name):
                    key = (c.ats, c.slug)
                    if key not in seen:
                        seen.add(key)
                        yield c
            log.info("HNPostsSource: scanned %d comments, %d unique slugs", count, len(seen))
