"""Tests for the daily slug discovery workflow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from allocation_agent.integrations.slug_sources import (
    HNPostsSource,
    GoogleSearchSource,
    LinkedInSource,
    OtherSource,
    SlugCandidate,
    load_slug_candidates,
)
from allocation_agent.integrations.slug_sources.hn_posts import _extract_from_text
from allocation_agent.integrations.slug_sources.other import _fetch_sitemap_slugs
from allocation_agent.integrations.allocation_crawler import get_existing_board_ids


# ── _extract_from_text ────────────────────────────────────────────────────────

def test_extract_greenhouse_url():
    text = "Apply at https://job-boards.greenhouse.io/acmecorp/jobs/12345"
    results = _extract_from_text(text, "hn_posts")
    assert len(results) == 1
    assert results[0].slug == "acmecorp"
    assert results[0].ats == "greenhouse"
    assert results[0].source == "hn_posts"


def test_extract_lever_url():
    text = "See openings at jobs.lever.co/bravo-labs/abc123"
    results = _extract_from_text(text, "hn_posts")
    assert any(r.slug == "bravo-labs" and r.ats == "lever" for r in results)


def test_extract_ashby_url():
    text = "We use jobs.ashbyhq.com/charliecorp for applications."
    results = _extract_from_text(text, "hn_posts")
    assert any(r.slug == "charliecorp" and r.ats == "ashby" for r in results)


def test_extract_deduplicates():
    text = (
        "job-boards.greenhouse.io/acmecorp/jobs/1 "
        "job-boards.greenhouse.io/acmecorp/jobs/2"
    )
    results = _extract_from_text(text, "hn_posts")
    slugs = [r.slug for r in results if r.ats == "greenhouse"]
    assert slugs.count("acmecorp") == 1


def test_extract_multiple_ats_in_one_comment():
    text = (
        "Greenhouse: boards.greenhouse.io/alpha | "
        "Lever: jobs.lever.co/beta | "
        "Ashby: jobs.ashbyhq.com/gamma"
    )
    results = _extract_from_text(text, "hn_posts")
    ats_slugs = {(r.ats, r.slug) for r in results}
    assert ("greenhouse", "alpha") in ats_slugs
    assert ("lever", "beta") in ats_slugs
    assert ("ashby", "gamma") in ats_slugs


# ── load_slug_candidates ──────────────────────────────────────────────────────

def test_load_slug_candidates_deduplicates():
    """Same (ats, slug) from two strategies → only one candidate."""
    fake_candidates_a = [
        SlugCandidate(slug="acme", company="Acme", ats="greenhouse", source="hn_posts"),
        SlugCandidate(slug="beta", company="Beta", ats="lever", source="hn_posts"),
    ]
    fake_candidates_b = [
        SlugCandidate(slug="acme", company="Acme Inc", ats="greenhouse", source="other"),
        SlugCandidate(slug="gamma", company="Gamma", ats="ashby", source="other"),
    ]

    with (
        patch.object(HNPostsSource, "iter_candidates", return_value=iter(fake_candidates_a)),
        patch.object(OtherSource, "iter_candidates", return_value=iter(fake_candidates_b)),
    ):
        results = load_slug_candidates(["hn_posts", "other"])

    slugs = [(r.ats, r.slug) for r in results]
    assert slugs.count(("greenhouse", "acme")) == 1
    assert ("lever", "beta") in slugs
    assert ("ashby", "gamma") in slugs


def test_load_slug_candidates_unknown_strategy_ignored():
    results = load_slug_candidates(["nonexistent_strategy"])
    assert results == []


def test_google_search_skips_when_no_key():
    src = GoogleSearchSource(api_key="")
    assert list(src.iter_candidates()) == []


# ── get_existing_board_ids ────────────────────────────────────────────────────

def test_get_existing_board_ids_parses_response():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "count": 2,
        "boards": [
            {"id": "coinbase", "company": "Coinbase", "ats": "greenhouse"},
            {"id": "figma", "company": "Figma", "ats": "greenhouse"},
        ],
    }
    with patch("allocation_agent.integrations.allocation_crawler.httpx.Client") as cls:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.return_value = mock_resp
        cls.return_value = client
        ids = get_existing_board_ids("https://example.com/api/crawler")
    assert ids == {"coinbase", "figma"}


def test_get_existing_board_ids_empty_on_empty_boards():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"count": 0, "boards": []}
    with patch("allocation_agent.integrations.allocation_crawler.httpx.Client") as cls:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.return_value = mock_resp
        cls.return_value = client
        ids = get_existing_board_ids("https://example.com/api/crawler")
    assert ids == set()


# ── sitemap extraction ────────────────────────────────────────────────────────

def test_fetch_sitemap_slugs_parses_xml():
    import re
    sitemap_xml = (
        "<?xml version='1.0'?><urlset>"
        "<url><loc>https://boards.greenhouse.io/acmecorp/jobs</loc></url>"
        "<url><loc>https://boards.greenhouse.io/betacorp</loc></url>"
        "</urlset>"
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = sitemap_xml
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    pat = re.compile(r"boards\.greenhouse\.io/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I)
    results = _fetch_sitemap_slugs(mock_client, "greenhouse", "https://boards.greenhouse.io/sitemap.xml", pat)
    slugs = [r.slug for r in results]
    assert "acmecorp" in slugs
    assert "betacorp" in slugs


def test_fetch_sitemap_slugs_skips_reserved_segments():
    import re
    sitemap_xml = (
        "<urlset><url><loc>https://boards.greenhouse.io/jobs/embed/api</loc></url>"
        "<url><loc>https://boards.greenhouse.io/realco</loc></url></urlset>"
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = sitemap_xml
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    pat = re.compile(r"boards\.greenhouse\.io/([a-zA-Z0-9][a-zA-Z0-9_-]+)", re.I)
    results = _fetch_sitemap_slugs(mock_client, "greenhouse", "https://boards.greenhouse.io/sitemap.xml", pat)
    slugs = [r.slug for r in results]
    assert "jobs" not in slugs
    assert "embed" not in slugs
    assert "api" not in slugs
    assert "realco" in slugs


# ── _run_discovery (integration-level) ────────────────────────────────────────

def test_run_discovery_dry_run_returns_summary():
    from allocation_agent.tasks.slug_discovery import _run_discovery

    fake_boards = {"coinbase", "figma"}
    fake_candidates = [
        SlugCandidate(slug="newco", company="NewCo", ats="greenhouse", source="hn_posts"),
        SlugCandidate(slug="coinbase", company="Coinbase", ats="greenhouse", source="hn_posts"),
    ]

    with (
        patch("allocation_agent.tasks.slug_discovery.get_existing_board_ids", return_value=fake_boards),
        patch("allocation_agent.tasks.slug_discovery.load_slug_candidates", return_value=fake_candidates),
    ):
        summary = _run_discovery(dry_run=True)

    assert summary["dry_run"] is True
    assert summary["candidates_found"] == 2
    assert summary["already_known"] == 1
    assert summary["newly_seeded"] == 1
    assert summary["new_boards"][0]["id"] == "newco"
    assert summary["errors"] == []


def test_run_discovery_seeds_only_new(monkeypatch):
    from allocation_agent.tasks.slug_discovery import _run_discovery
    from allocation_agent.config import settings

    monkeypatch.setattr(settings, "alloc_crawler_api_key", "")

    fake_boards: set[str] = set()
    fake_candidates = [
        SlugCandidate(slug="alpha", company="Alpha", ats="lever", source="other"),
    ]

    seeded: list[dict] = []

    def fake_seed_board(api_base, board_id, company, ats, career_page_url="", api_key=""):
        seeded.append({"id": board_id, "ats": ats})
        return {"id": board_id}

    with (
        patch("allocation_agent.tasks.slug_discovery.get_existing_board_ids", return_value=fake_boards),
        patch("allocation_agent.tasks.slug_discovery.load_slug_candidates", return_value=fake_candidates),
        patch("allocation_agent.tasks.slug_discovery.seed_board", side_effect=fake_seed_board),
    ):
        summary = _run_discovery(dry_run=False)

    assert summary["newly_seeded"] == 1
    assert seeded[0]["id"] == "alpha"


def test_run_discovery_skips_409_conflict():
    from allocation_agent.tasks.slug_discovery import _run_discovery

    fake_candidates = [
        SlugCandidate(slug="existing", company="Existing", ats="greenhouse", source="other"),
    ]

    mock_response = MagicMock()
    mock_response.status_code = 409

    with (
        patch("allocation_agent.tasks.slug_discovery.get_existing_board_ids", return_value=set()),
        patch("allocation_agent.tasks.slug_discovery.load_slug_candidates", return_value=fake_candidates),
        patch(
            "allocation_agent.tasks.slug_discovery.seed_board",
            side_effect=httpx.HTTPStatusError("conflict", request=MagicMock(), response=mock_response),
        ),
    ):
        summary = _run_discovery(dry_run=False)

    assert summary["errors"] == []
    assert summary["newly_seeded"] == 0
