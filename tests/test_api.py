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


def test_dashboard_queues_uses_redis_llen(monkeypatch):
    from allocation_agent.web import dashboard

    class _FakeRedis:
        def llen(self, name):
            return {"select": 12, "apply": 3, "feedback": 0}[name]

    monkeypatch.setattr(dashboard, "_redis", lambda: _FakeRedis())
    client = TestClient(dashboard.app)
    r = client.get("/api/queues")
    assert r.status_code == 200
    assert r.json() == {"queues": {"select": 12, "apply": 3, "feedback": 0}}


def test_dashboard_queues_returns_none_when_redis_down(monkeypatch):
    from allocation_agent.web import dashboard

    def _boom():
        raise ConnectionError("nope")

    monkeypatch.setattr(dashboard, "_redis", _boom)
    client = TestClient(dashboard.app)
    r = client.get("/api/queues")
    assert r.status_code == 200
    assert r.json() == {"queues": {"select": None, "apply": None, "feedback": None}}


def test_dashboard_workers_summarises_inspect(monkeypatch):
    from allocation_agent.web import dashboard
    from allocation_agent import celery_app as ca

    dashboard._inspect_cache["ts"] = 0.0
    dashboard._inspect_cache["value"] = None

    class _FakeInspect:
        def active(self):
            return {"worker@h1": [{"id": "t1"}, {"id": "t2"}]}

        def registered(self):
            return {"worker@h1": ["task.a", "task.b", "task.c"]}

    class _FakeControl:
        def inspect(self, timeout=1.0):
            return _FakeInspect()

    monkeypatch.setattr(ca.app, "control", _FakeControl())
    client = TestClient(dashboard.app)
    r = client.get("/api/workers")
    assert r.status_code == 200
    body = r.json()
    assert body["workers"] == {"worker@h1": {"active": 2, "registered_tasks": 3}}

