from pathlib import Path

import pytest

from allocation_agent.config import settings
from allocation_agent.sources.dover import (
    is_relevant,
    load_dover_candidates,
    score_priority,
)


def test_load_mock_fixture():
    jobs = load_dover_candidates(settings.dover_jobs_path)
    ids = {j.job_id for j in jobs}
    assert "nyc-001-backend" in ids
    assert "filter-intern" not in ids
    assert "filter-eu" not in ids
    assert jobs[0].expected_callback_prob >= jobs[-1].expected_callback_prob


def test_load_invalid_json(tmp_path: Path):
    import json

    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        load_dover_candidates(bad)


def test_is_relevant_matrix():
    assert is_relevant("Senior Software Engineer", "New York, NY")
    assert not is_relevant("Software Engineer Intern", "")
    assert not is_relevant("Senior Software Engineer", "Berlin, Germany")


def test_score_priority_ordering():
    a = score_priority("Software Engineer (Remote)")
    b = score_priority("Senior Software Engineer — New York City")
    assert b > a

