"""CrawlerSource HTTP mode (finder-mock-compatible /v1/jobs)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from allocation_agent.config import settings
from allocation_agent.sources.crawler import CrawlerSource


def test_crawler_http_fetches_jobs_json(monkeypatch) -> None:
    monkeypatch.setattr(settings, "crawler_http_backend", "finder")
    payload = {
        "jobs": [
            {
                "job_id": "f-1",
                "company_id": "ex-com",
                "ats": "unknown",
                "title": "Role",
                "apply_url": "https://careers.example.com/j/1",
                "posted_at": 1,
                "expected_callback_prob": 0.77,
            }
        ],
        "next_cursor": None,
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = payload

    with patch("allocation_agent.sources.crawler.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.return_value = mock_resp
        client_cls.return_value = client

        src = CrawlerSource(use_http=True, base_url="http://test.invalid:9")
        rows = src._fetch()

    assert len(rows) == 1
    assert rows[0]["job_id"] == "f-1"
    client.get.assert_called_once()
    call_kw = client.get.call_args
    assert call_kw[0][0] == "http://test.invalid:9/v1/jobs"
    assert call_kw[1]["params"] == {"limit": 1000}


def test_crawler_http_empty_on_error(monkeypatch) -> None:
    monkeypatch.setattr(settings, "crawler_http_backend", "finder")
    with patch("allocation_agent.sources.crawler.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = httpx.ConnectError("refused", request=MagicMock())
        client_cls.return_value = client

        src = CrawlerSource(use_http=True, base_url="http://127.0.0.1:1")
        assert src._fetch() == []


def test_crawler_http_allocation_crawler_path(monkeypatch) -> None:
    monkeypatch.setattr(settings, "crawler_http_backend", "allocation_crawler")
    monkeypatch.setattr(settings, "crawler_alloc_board", "coinbase")
    monkeypatch.setattr(settings, "crawler_alloc_max_rows", 50)
    api = {
        "count": 1,
        "jobs": [
            {
                "job_id": "1",
                "board": "coinbase",
                "title": "Engineer",
                "url": "https://x.com/positions/1?gh_jid=1",
                "status": "discovered",
                "discovered_at": "2026-01-15T00:00:00.000Z",
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api
    with patch("allocation_agent.sources.crawler.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.return_value = mock_resp
        client_cls.return_value = client
        src = CrawlerSource(use_http=True, base_url="https://example.net/api/crawler")
        rows = src._fetch()
    assert len(rows) == 1
    assert rows[0]["job_id"] == "1"
    assert rows[0]["ats"] == "greenhouse"
    assert client.get.call_args[0][0] == "https://example.net/api/crawler/jobs"
    p = client.get.call_args[1]["params"]
    assert p["status"] == "discovered" and p["board"] == "coinbase"
