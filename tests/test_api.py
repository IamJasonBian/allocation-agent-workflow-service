from fastapi.testclient import TestClient


def test_dashboard_health(memory_db):
    from allocation_agent.web.dashboard import app

    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["apply_mode"] == "mock"


def test_dashboard_outcomes(memory_db):
    from allocation_agent.stores.feedback import record_outcome
    from allocation_agent.schemas import ApplyOutcome
    from allocation_agent.web.dashboard import app

    record_outcome(
        ApplyOutcome(
            candidate_id="a",
            job_id="b",
            ats="unknown",
            status="submitted",
        )
    )
    client = TestClient(app)
    r = client.get("/api/outcomes?limit=5")
    assert r.status_code == 200
    assert len(r.json()) >= 1

