"""Unit tests for the applications ledger (stores/feedback.py)."""

from datetime import datetime, timedelta

import pytest

from allocation_agent.schemas import ApplyOutcome, JobCandidate
from allocation_agent.stores.feedback import (
    ApplicationRow,
    ensure_applications,
    get_engine,
    list_applications,
    pick_work,
    reclaim_expired_leases,
    record_outcome,
    transition_on_outcome,
)
from sqlalchemy.orm import Session


def _cand(job_id: str, company_id: str = "co-x", p: float = 0.5) -> JobCandidate:
    return JobCandidate(
        job_id=job_id,
        company_id=company_id,
        ats="unknown",
        title="Test Role",
        apply_url=f"https://example.test/{job_id}",
        posted_at=0,
        expected_callback_prob=p,
    )


def _outcome(job_id: str, status: str, candidate_id: str = "c1") -> ApplyOutcome:
    return ApplyOutcome(
        candidate_id=candidate_id,
        job_id=job_id,
        ats="unknown",
        status=status,
        message=f"test {status}",
    )


def _set_state(candidate_id: str, job_id: str, state: str, wait_until=None):
    with Session(get_engine()) as s:
        row = s.get(ApplicationRow, (candidate_id, job_id))
        row.state = state
        row.wait_until = wait_until
        s.commit()


def test_ensure_applications_is_idempotent(memory_db):
    cands = [_cand("j1"), _cand("j2"), _cand("j3")]
    assert ensure_applications("c1", cands) == 3
    assert ensure_applications("c1", cands) == 0  # second call inserts zero
    assert len(list_applications("c1")) == 3


def test_pick_work_skips_non_eligible_states(memory_db):
    ensure_applications("c1", [_cand("j1"), _cand("j2"), _cand("j3")])
    _set_state("c1", "j2", "done")
    _set_state("c1", "j3", "abandoned")

    picked = pick_work("c1", limit=5)
    assert {p[1] for p in picked} == {"j1"}


def test_pick_work_respects_backoff(memory_db):
    ensure_applications("c1", [_cand("j1"), _cand("j2")])
    _set_state("c1", "j1", "eligible", datetime.utcnow() + timedelta(hours=1))
    # j2 left with wait_until=NULL (pickable now)

    picked = pick_work("c1", limit=5)
    assert {p[1] for p in picked} == {"j2"}


def test_pick_work_reclaims_expired_lease(memory_db):
    ensure_applications("c1", [_cand("j1")])
    _set_state("c1", "j1", "in_flight", datetime.utcnow() - timedelta(minutes=5))

    picked = pick_work("c1", limit=5)
    assert picked == [("c1", "j1")]


def test_pick_work_skips_live_lease(memory_db):
    ensure_applications("c1", [_cand("j1")])
    _set_state("c1", "j1", "in_flight", datetime.utcnow() + timedelta(minutes=5))

    picked = pick_work("c1", limit=5)
    assert picked == []


def test_pick_work_preserves_preferred_order(memory_db):
    ensure_applications("c1", [_cand("j1"), _cand("j2"), _cand("j3"), _cand("j4")])
    picked = pick_work("c1", limit=2, preferred_job_ids=["j3", "j1", "j4", "j2"])
    assert [p[1] for p in picked] == ["j3", "j1"]


def test_transition_submitted_to_done(memory_db):
    ensure_applications("c1", [_cand("j1")])
    _set_state("c1", "j1", "in_flight", datetime.utcnow() + timedelta(minutes=5))
    record_outcome(_outcome("j1", "submitted"))
    state = transition_on_outcome(_outcome("j1", "submitted"))
    assert state == "done"


@pytest.mark.parametrize(
    "status,expected_state",
    [
        ("captcha", "eligible"),
        ("blocked", "eligible"),
        ("interrupted", "eligible"),
        ("skipped", "done"),
        ("needs_auth", "abandoned"),
    ],
)
def test_transition_status_to_state(memory_db, status, expected_state):
    ensure_applications("c1", [_cand("j1")])
    record_outcome(_outcome("j1", status))
    state = transition_on_outcome(_outcome("j1", status))
    assert state == expected_state


def test_error_backoff_and_abandonment(memory_db):
    ensure_applications("c1", [_cand("j1")])
    # First two errors → eligible with exp backoff
    for _ in range(2):
        record_outcome(_outcome("j1", "error"))
        state = transition_on_outcome(_outcome("j1", "error"))
        assert state == "eligible"
    # Third error → abandoned
    record_outcome(_outcome("j1", "error"))
    state = transition_on_outcome(_outcome("j1", "error"))
    assert state == "abandoned"


def test_transition_creates_row_if_missing(memory_db):
    # Simulates retroactive outcome ingest where no selector pick happened.
    record_outcome(_outcome("orphan-job", "submitted"))
    state = transition_on_outcome(_outcome("orphan-job", "submitted"))
    assert state == "done"
    rows = list_applications("c1")
    assert any(r["job_id"] == "orphan-job" for r in rows)


def test_reclaim_expired_leases(memory_db):
    ensure_applications("c1", [_cand("j1"), _cand("j2"), _cand("j3")])
    _set_state("c1", "j1", "in_flight", datetime.utcnow() - timedelta(minutes=30))  # expired
    _set_state("c1", "j2", "in_flight", datetime.utcnow() + timedelta(minutes=30))  # live
    # j3 stays eligible

    reclaimed = reclaim_expired_leases()
    assert reclaimed == 1

    rows = {r["job_id"]: r for r in list_applications("c1")}
    assert rows["j1"]["state"] == "eligible"
    assert rows["j1"]["wait_until"] is None   # clears the lease time
    assert rows["j2"]["state"] == "in_flight"  # live lease untouched
    assert rows["j3"]["state"] == "eligible"


def test_tick_random_sample_differs_from_ranked(memory_db, celery_eager, monkeypatch):
    """--random should shuffle the rank, so two different seeds produce different dispatches."""
    from allocation_agent.config import settings
    from allocation_agent.stores.feedback import list_applications
    from allocation_agent.tasks.select import tick

    monkeypatch.setattr(settings, "apply_mode", "mock")
    monkeypatch.setattr(settings, "mock_apply_determinism", 0)   # all 'submitted' → done

    tick("rng-a", queue_size=2, random_sample=True, seed=1)
    picked_a = {r["job_id"] for r in list_applications("rng-a") if r["state"] == "done"}

    tick("rng-b", queue_size=2, random_sample=True, seed=2)
    picked_b = {r["job_id"] for r in list_applications("rng-b") if r["state"] == "done"}

    # Different seeds → different samples (very unlikely to collide entirely on a
    # corpus of more than 2 candidates).
    assert picked_a != picked_b


def test_tick_random_sample_reproducible_with_seed(memory_db, celery_eager, monkeypatch):
    """Same seed → same pick set across runs (regression-friendly)."""
    from allocation_agent.config import settings
    from allocation_agent.stores.feedback import list_applications
    from allocation_agent.tasks.select import tick

    monkeypatch.setattr(settings, "apply_mode", "mock")
    monkeypatch.setattr(settings, "mock_apply_determinism", 0)

    tick("seed-a", queue_size=2, random_sample=True, seed=42)
    set_a = {r["job_id"] for r in list_applications("seed-a") if r["state"] == "done"}

    tick("seed-b", queue_size=2, random_sample=True, seed=42)
    set_b = {r["job_id"] for r in list_applications("seed-b") if r["state"] == "done"}

    assert set_a == set_b


def test_reclaim_expired_leases_scoped_to_candidate(memory_db):
    ensure_applications("cA", [_cand("j1")])
    ensure_applications("cB", [_cand("j1")])
    _set_state("cA", "j1", "in_flight", datetime.utcnow() - timedelta(minutes=5))
    _set_state("cB", "j1", "in_flight", datetime.utcnow() - timedelta(minutes=5))

    # Only reclaim cA's rows.
    assert reclaim_expired_leases("cA") == 1
    rows_b = {r["job_id"]: r for r in list_applications("cB")}
    assert rows_b["j1"]["state"] == "in_flight"   # cB still in_flight
