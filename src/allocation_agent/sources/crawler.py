"""CrawlerSource — canonical JobCandidate feed from HTTP backends or mocks.

- **Mock** (default, ``crawler_use_http=False``): in-process list for tests.
- **finder** (``crawler_use_http`` + ``crawler_http_backend=finder``): GET
  ``{crawler_base_url}/v1/jobs`` (finder-mock).
- **allocation_crawler** (``crawler_http_backend=allocation_crawler``): GET
  ``{crawler_base_url}/jobs?status=discovered`` — Netlify service
  (e.g. ``https://allocation-crawler-service.netlify.app/api/crawler``). Map rows to
  :class:`JobCandidate`. Use ``crawler_alloc_board`` to limit scope. Frontier-style
  Greenhouse list URLs: ``integrations.allocation_crawler.greenhouse_board_frontier_url``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx

from ..config import settings
from ..schemas import JobCandidate

log = logging.getLogger(__name__)


def _iso_to_unix_utc(s: str | None) -> int:
    if not s:
        return 0
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp())
    except (ValueError, OSError, TypeError):
        return 0


def _ats_from_url(url: str) -> str:
    u = (url or "").lower()
    if "gh_jid" in u or "greenhouse.io" in u or "job-boards.greenhouse" in u:
        return "greenhouse"
    if "lever.co" in u or "jobs.lever" in u:
        return "lever"
    if "ashbyhq" in u or "jobs.ashby" in u:
        return "ashby"
    return "unknown"


def _prob_from_crawler_row(r: dict) -> float:
    t = f"{r.get('title', '')} {r.get('department', '')}".lower()
    s = 0.52
    if "senior" in t or "sr " in t or "sr." in t:
        s += 0.1
    if any(k in t for k in ("engineer", "backend", "frontend", "ml ", "swe")):
        s += 0.06
    tags = r.get("tags")
    if isinstance(tags, list) and any("engineer" in str(x).lower() for x in tags):
        s += 0.04
    return min(0.95, s)


def map_allocation_crawler_row_to_raw(r: dict) -> dict | None:
    """Map Netlify job JSON to ``JobCandidate`` field dict, or return None to skip."""
    u = (r.get("url") or "").strip()
    if not u:
        return None
    jid = r.get("job_id")
    if jid is None:
        return None
    board = str(r.get("board") or "unknown")
    da = r.get("discovered_at")
    ua = r.get("updated_at")
    posted = _iso_to_unix_utc(da) if isinstance(da, str) else 0
    if not posted and isinstance(ua, str):
        posted = _iso_to_unix_utc(ua)
    return {
        "job_id": str(jid),
        "company_id": board,
        "ats": _ats_from_url(u),  # type: ignore[dict-item]
        "title": (r.get("title") or "Unknown title").strip() or "Unknown title",
        "apply_url": u,
        "posted_at": posted,
        "expected_callback_prob": _prob_from_crawler_row(r),
    }


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
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.crawler_base_url)
        self.state_path = state_path
        if use_http is None:
            self.use_http = settings.crawler_use_http
        else:
            self.use_http = use_http
        # Optional: inject a shared httpx client (e.g. tests, ASGI transport, tracing).
        self._http_client = http_client

    def iter_candidates(self) -> Iterable[JobCandidate]:
        for raw in self._fetch():
            yield JobCandidate(**raw)

    def _fetch(self) -> list[dict]:
        if self.use_http:
            return self._fetch_http()
        return list(_MOCK_CANDIDATES)

    def _fetch_http(self) -> list[dict]:
        base = str(self.base_url or settings.crawler_base_url).rstrip("/")
        if settings.crawler_http_backend == "allocation_crawler":
            return self._fetch_allocation_crawler_http(base)
        return self._fetch_finder_http(base)

    def _fetch_finder_http(self, base: str) -> list[dict]:
        url = f"{base}/v1/jobs"
        try:
            if self._http_client is not None:
                r = self._http_client.get(url, params={"limit": 1000})
            else:
                with httpx.Client(timeout=60.0) as client:
                    r = client.get(url, params={"limit": 1000})
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

    def _fetch_allocation_crawler_http(self, base: str) -> list[dict]:
        """``GET {base}/jobs?status=discovered`` — public Netlify service."""
        url = f"{base}/jobs"
        params: dict[str, str] = {"status": "discovered"}
        b = (settings.crawler_alloc_board or "").strip()
        if b:
            params["board"] = b
        cap = max(1, min(settings.crawler_alloc_max_rows, 10_000))
        if not b:
            log.warning(
                "crawler: allocation_crawler with no crawler_alloc_board — "
                "capping to %s rows; set a board to narrow",
                cap,
            )
        try:
            if self._http_client is not None:
                r = self._http_client.get(url, params=params, timeout=120.0)
            else:
                with httpx.Client(timeout=120.0) as client:
                    r = client.get(url, params=params)
            r.raise_for_status()
            payload = r.json()
        except (httpx.HTTPError, OSError, ValueError) as e:
            log.warning("allocation_crawler fetch failed: %s", e)
            return []
        raw_jobs = payload.get("jobs")
        if not isinstance(raw_jobs, list):
            return []
        rows = raw_jobs[:cap]
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            m = map_allocation_crawler_row_to_raw(row)
            if m is not None:
                out.append(m)
        return out

    def _load_hwm(self) -> str | None:
        if self.state_path and self.state_path.exists():
            return self.state_path.read_text().strip() or None
        return None

    def _save_hwm(self, cursor: str) -> None:
        if self.state_path is not None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(cursor)
