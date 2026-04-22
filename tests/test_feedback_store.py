from allocation_agent.schemas import ApplyOutcome, CallbackSignal
from allocation_agent.stores.feedback import recent_outcomes, record_callback, record_outcome


def test_record_outcome_and_recent(memory_db):
    oid = record_outcome(
        ApplyOutcome(
            candidate_id="u1",
            job_id="j1",
            ats="greenhouse",
            status="submitted",
            message="ok",
        )
    )
    assert oid >= 1
    rows = recent_outcomes(10)
    assert len(rows) == 1
    assert rows[0]["job_id"] == "j1"


def test_record_callback(memory_db):
    cid = record_callback(
        CallbackSignal(candidate_id="u1", job_id="j1", kind="callback", raw="ping")
    )
    assert cid >= 1

