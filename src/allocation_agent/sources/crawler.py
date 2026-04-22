"""CrawlerSource — canonical JobCandidate feed from the finder / crawler service.

- **Mock** (default): fixed in-process list so tests and dry runs need no network.
- **HTTP** (`settings.crawler_use_http`): GET ``{crawler_base_url}/v1/jobs`` — matches
  the `finder-mock` read API. Seed work via
  `allocation_agent.integrations.finder.seed_finder_url` or …/v1/seed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import httpx

from ..config import settings
from ..schemas import JobCandidate

log = logging.getLogger(__name__)


_MOCK_CANDIDATES: list[dict] = [
    {
        "job_id": "crawler-mock-0001",
        "company_id": "acme",
        "ats": "greenhouse",
        "title": "Senior Software Engineer",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/mock-0001",
        "posted_at": 1745280000,
        "expected_callback_prob": 0.78,
    },
    {
        "job_id": "crawler-mock-0002",
        "company_id": "bravo-labs",
        "ats": "lever",
        "title": "Senior Platform Engineer",
        "apply_url": "https://jobs.lever.co/bravo-labs/mock-0002",
        "posted_at": 1745283600,
        "expected_callback_prob": 0.72,
    },
    {
        "job_id": "crawler-mock-0003",
        "company_id": "charlie",
        "ats": "ashby",
        "title": "Software Engineer, Full Stack",
        "apply_url": "https://jobs.ashbyhq.com/charlie/mock-0003",
        "posted_at": 1745290800,
        "expected_callback_prob": 0.65,
    },
    {
        "job_id": "crawler-mock-0004",
        "company_id": "delta",
        "ats": "workday",
        "title": "Senior Software Engineer, Backend",
        "apply_url": "https://delta.wd5.myworkdayjobs.com/mock-0004",
        "posted_at": 1745294400,
        "expected_callback_prob": 0.60,
    },
    {
        # Deliberate collision with DoverSource fixture — proves cross-source
        # dedupe via load_candidates().
        "job_id": "nyc-001-backend",
        "company_id": "exampleco",
        "ats": "greenhouse",
        "title": "Senior Backend Engineer — NYC",
        "apply_url": "https://example.com/jobs/nyc-001",
        "posted_at": 1745298000,
        "expected_callback_prob": 0.88,
    },
]


class CrawlerSource:
    """JobCandidate feed from the crawler (mock list or HTTP to finder-mock / future API)."""

    name = "crawler"

    def __init__(
        self,
        base_url: str | None = None,
        state_path: Path | None = None,
        use_http: bool | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.crawler_base_url)
        self.state_path = state_path
        if use_http is None:
            self.use_http = settings.crawler_use_http
        else:
            self.use_http = use_http

    def iter_candidates(self) -> Iterable[JobCandidate]:
        for raw in self._fetch():
            yield JobCandidate(**raw)

    def _fetch(self) -> list[dict]:
        if self.use_http:
            return self._fetch_http()
        return list(_MOCK_CANDIDATES)

    def _fetch_http(self) -> list[dict]:
        base = str(self.base_url or settings.crawler_base_url).rstrip("/")
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(f"{base}/v1/jobs", params={"limit": 1000})
                r.raise_for_status()
                payload = r.json()
        except (httpx.HTTPError, OSError, ValueError) as e:
            log.warning("crawler HTTP fetch failed: %s", e)
            return []
        raw_jobs = payload.get("jobs")
        if not isinstance(raw_jobs, list):
            return []
        out: list[dict] = []
        for row in raw_jobs:
            if isinstance(row, dict):
                out.append(row)
        return out

    def _load_hwm(self) -> str | None:
        if self.state_path and self.state_path.exists():
            return self.state_path.read_text().strip() or None
        return None

    def _save_hwm(self, cursor: str) -> None:
        if self.state_path is not None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(cursor)
