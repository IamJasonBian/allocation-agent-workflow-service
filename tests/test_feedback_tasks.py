import pytest

from allocation_agent.tasks.feedback import record_callback_task, record_outcome_task


def test_record_outcome_task_invalid_payload(memory_db):
    with pytest.raises(Exception):
        record_outcome_task.run({"bad": "payload"})


def test_record_callback_task_invalid_payload(memory_db):
    with pytest.raises(Exception):
        record_callback_task.run({"candidate_id": "x"})


def test_record_outcome_task_ok(memory_db):
    rid = record_outcome_task.run(
        {
            "candidate_id": "a",
            "job_id": "b",
            "ats": "unknown",
            "status": "submitted",
            "message": "",
            "tokens_spent": 0,
            "wallclock_ms": 0,
        }
    )
    assert isinstance(rid, int)


def test_record_outcome_task_transitions_ledger(memory_db):
    from allocation_agent.stores.feedback import list_applications

    record_outcome_task.run(
        {
            "candidate_id": "a",
            "job_id": "b",
            "ats": "unknown",
            "status": "submitted",
            "message": "",
            "tokens_spent": 0,
            "wallclock_ms": 0,
        }
    )
    rows = {r["job_id"]: r for r in list_applications("a")}
    assert rows["b"]["state"] == "done"


def test_record_outcome_task_captcha_sets_backoff(memory_db):
    from allocation_agent.stores.feedback import list_applications

    record_outcome_task.run(
        {
            "candidate_id": "a",
            "job_id": "b",
            "ats": "unknown",
            "status": "captcha",
            "message": "",
        }
    )
    rows = {r["job_id"]: r for r in list_applications("a")}
    assert rows["b"]["state"] == "eligible"
    assert rows["b"]["wait_until"] is not None  # backoff set
