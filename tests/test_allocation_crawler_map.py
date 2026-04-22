import pytest

from allocation_agent.schemas import JobCandidate
from allocation_agent.sources.crawler import map_allocation_crawler_row_to_raw


def test_map_crawler_row_realistic_coinbase() -> None:
    row = {
        "job_id": "7609632",
        "board": "coinbase",
        "title": "Senior Software Engineer",
        "url": "https://www.coinbase.com/careers/positions/7609632?gh_jid=7609632",
        "location": "NYC",
        "department": "Eng",
        "status": "discovered",
        "discovered_at": "2026-04-11T12:00:00.000Z",
        "tags": ["engineering", "senior"],
    }
    raw = map_allocation_crawler_row_to_raw(row)
    assert raw is not None
    c = JobCandidate(**raw)
    assert c.company_id == "coinbase"
    assert c.ats == "greenhouse"
    assert "gh_jid" in c.apply_url
    assert c.posted_at > 0


def test_map_crawler_row_skips_empty_url() -> None:
    assert map_allocation_crawler_row_to_raw({"job_id": "1", "url": ""}) is None
