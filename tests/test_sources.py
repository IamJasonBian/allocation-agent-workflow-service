from typing import Iterable

import pytest

from allocation_agent.schemas import JobCandidate
from allocation_agent.sources import (
    JobSource,
    load_candidates,
    resolve_sources,
)


class _StaticSource:
    def __init__(self, name: str, cands: list[JobCandidate]) -> None:
        self.name = name
        self._cands = cands

    def iter_candidates(self) -> Iterable[JobCandidate]:
        yield from self._cands


def _make(job_id: str, company_id: str, p: float) -> JobCandidate:
    return JobCandidate(
        job_id=job_id,
        company_id=company_id,
        ats="unknown",
        title="Test Role",
        apply_url=f"https://example.test/{job_id}",
        posted_at=0,
        expected_callback_prob=p,
    )


def test_static_source_is_a_jobsource():
    assert isinstance(_StaticSource("x", []), JobSource)


def test_load_candidates_sorts_by_score_desc():
    src = _StaticSource(
        "a",
        [_make("j1", "co-a", 0.5), _make("j2", "co-b", 0.9), _make("j3", "co-c", 0.1)],
    )
    out = load_candidates([src])
    assert [c.job_id for c in out] == ["j2", "j1", "j3"]


def test_load_candidates_dedupes_keeping_higher_score():
    low = _StaticSource("low", [_make("j1", "co-a", 0.3)])
    high = _StaticSource("high", [_make("j1", "co-a", 0.8)])
    out = load_candidates([low, high])
    assert len(out) == 1
    assert out[0].expected_callback_prob == 0.8


def test_load_candidates_dedupe_key_is_company_plus_job():
    # same job_id under different company → two distinct candidates
    a = _StaticSource("a", [_make("j1", "co-a", 0.4)])
    b = _StaticSource("b", [_make("j1", "co-b", 0.6)])
    out = load_candidates([a, b])
    assert {(c.company_id, c.job_id) for c in out} == {("co-a", "j1"), ("co-b", "j1")}


def test_resolve_sources_default_has_dover():
    out = resolve_sources()
    assert any(getattr(s, "name", "") == "dover" for s in out)


def test_resolve_sources_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown source"):
        resolve_sources(["not-a-source"])


def test_load_candidates_real_default_sources_returns_list():
    # Smoke: default config loads the mock Dover fixture without error.
    out = load_candidates()
    assert isinstance(out, list)
    assert all(isinstance(c, JobCandidate) for c in out)
