"""Source-agnostic candidate loader.

Each `JobSource` emits its own filtered, scored candidates. The loader merges
results across sources, dedupes on `(company_id, job_id)` keeping the
highest-scoring duplicate, and returns a single sorted list for the selector.

Add a new source by:
  1. implementing the `JobSource` protocol in `sources/<name>.py`
  2. registering it in `_REGISTRY` below
  3. adding its name to `settings.enabled_sources`
"""

from typing import Callable, Iterable, Optional

from ..config import settings
from ..schemas import JobCandidate
from .base import JobSource
from .crawler import CrawlerSource
from .dover import DoverSource


_REGISTRY: dict[str, Callable[[], JobSource]] = {
    "dover": lambda: DoverSource(),
    "crawler": lambda: CrawlerSource(
        base_url=settings.crawler_base_url,
        state_path=settings.crawler_state_path,
        use_http=settings.crawler_use_http,
    ),
}


def resolve_sources(names: Iterable[str] | None = None) -> list[JobSource]:
    selected = list(names) if names is not None else list(settings.enabled_sources)
    out: list[JobSource] = []
    for n in selected:
        factory = _REGISTRY.get(n)
        if factory is None:
            raise ValueError(
                f"unknown source: {n!r} (known: {sorted(_REGISTRY)})"
            )
        out.append(factory())
    return out


def load_candidates(
    sources: Optional[list[JobSource]] = None,
) -> list[JobCandidate]:
    """Merge + dedupe + sort candidates across all active sources."""
    active = sources if sources is not None else resolve_sources()

    by_key: dict[tuple[str, str], JobCandidate] = {}
    for src in active:
        for cand in src.iter_candidates():
            key = (cand.company_id, cand.job_id)
            prev = by_key.get(key)
            if prev is None or cand.expected_callback_prob > prev.expected_callback_prob:
                by_key[key] = cand

    ranked = list(by_key.values())
    ranked.sort(key=lambda c: c.expected_callback_prob, reverse=True)
    return ranked


__all__ = [
    "JobSource",
    "DoverSource",
    "CrawlerSource",
    "load_candidates",
    "resolve_sources",
]
