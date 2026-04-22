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
