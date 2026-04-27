"""Slug discovery source registry.

Each source implements the :class:`SlugSource` protocol and yields
:class:`SlugCandidate` objects. :func:`load_slug_candidates` merges all
enabled sources and deduplicates on ``(ats, slug)``.
"""

from __future__ import annotations

from .base import SlugCandidate, SlugSource
from .google_search import GoogleSearchSource
from .hn_posts import HNPostsSource
from .linkedin import LinkedInSource
from .other import OtherSource

__all__ = [
    "SlugCandidate",
    "SlugSource",
    "HNPostsSource",
    "GoogleSearchSource",
    "LinkedInSource",
    "OtherSource",
    "load_slug_candidates",
]


def load_slug_candidates(
    enabled_strategies: list[str],
    serpapi_key: str = "",
    li_at_cookie: str = "",
    include_yc: bool = False,
) -> list[SlugCandidate]:
    """Merge slug candidates from all enabled discovery strategies.

    Deduplicates on ``(ats, slug)``; first source to yield a slug wins.
    """
    sources: list[SlugSource] = []
    for name in enabled_strategies:
        if name == "hn_posts":
            sources.append(HNPostsSource())
        elif name == "google_search":
            sources.append(GoogleSearchSource(api_key=serpapi_key))
        elif name == "linkedin":
            sources.append(LinkedInSource(li_at_cookie=li_at_cookie))
        elif name == "other":
            sources.append(OtherSource(include_yc=include_yc))

    all_candidates: list[SlugCandidate] = []
    seen: set[tuple[str, str]] = set()
    for src in sources:
        for c in src.iter_candidates():
            key = (c.ats, c.slug)
            if key not in seen:
                seen.add(key)
                all_candidates.append(c)
    return all_candidates
