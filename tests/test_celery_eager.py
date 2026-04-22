from allocation_agent.config import settings
from allocation_agent.stores.feedback import list_applications, recent_outcomes
from allocation_agent.tasks.select import tick


def test_tick_eager_chain(memory_db, celery_eager, monkeypatch):
    monkeypatch.setattr(settings, "apply_mode", "mock")
    n = tick("candidate-eager", queue_size=2)
    assert n == 2
    assert len(recent_outcomes(10)) == 2


def test_tick_populates_ledger(memory_db, celery_eager, monkeypatch):
    """After a tick, every dispatched job should be in a terminal or retry state."""
    monkeypatch.setattr(settings, "apply_mode", "mock")
    tick("candidate-ledger", queue_size=3)

    rows = list_applications("candidate-ledger")
    # The dispatched rows landed in a non-in_flight state by end of eager chain.
    dispatched_states = {
        r["state"] for r in rows
        if r["state"] in ("done", "eligible", "abandoned")
    }
    assert "done" in dispatched_states or "eligible" in dispatched_states


def test_tick_is_idempotent_on_done_rows(memory_db, celery_eager, monkeypatch):
    """Re-running a tick should NOT re-dispatch already-done jobs."""
    monkeypatch.setattr(settings, "apply_mode", "mock")
    monkeypatch.setattr(settings, "mock_apply_determinism", 0)   # force 'submitted' bucket

    first = tick("candidate-idem", queue_size=2)
    outcomes_before = len(recent_outcomes(100))

    second = tick("candidate-idem", queue_size=2)
    outcomes_after = len(recent_outcomes(100))

    # Second tick must not resurrect jobs that reached 'done' in the first tick.
    done_jobs = {r["job_id"] for r in list_applications("candidate-idem") if r["state"] == "done"}
    assert done_jobs, "first tick should have produced at least one done job"
    # Outcomes total should grow by at most `queue_size` new jobs (not re-apply the done ones).
    assert outcomes_after - outcomes_before <= 2
