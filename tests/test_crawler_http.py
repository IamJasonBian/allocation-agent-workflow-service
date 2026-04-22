"""CrawlerSource HTTP mode (finder-mock-compatible /v1/jobs)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from allocation_agent.sources.crawler import CrawlerSource


def test_crawler_http_fetches_jobs_json() -> None:
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


def test_crawler_http_empty_on_error() -> None:
    with patch("allocation_agent.sources.crawler.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = httpx.ConnectError("refused", request=MagicMock())
        client_cls.return_value = client

        src = CrawlerSource(use_http=True, base_url="http://127.0.0.1:1")
        assert src._fetch() == []
