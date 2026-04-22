from allocation_agent.config import settings
from allocation_agent.schemas import AgentDispatch, ApplyOutcome, JobCandidate
from allocation_agent.tasks.apply import _run_mock_apply, execute_apply


def _dispatch(job_id: str = "nyc-001-backend") -> AgentDispatch:
    job = JobCandidate(
        job_id=job_id,
        company_id="co",
        ats="greenhouse",
        title="Engineer",
        apply_url="https://example.com/j",
        posted_at=0,
        expected_callback_prob=0.9,
    )
    return AgentDispatch(candidate_id="c1", job=job, reason="test")


def test_execute_apply_mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "apply_mode", "mock")
    out = execute_apply(_dispatch())
    assert out.status in ("submitted", "captcha", "error")
    assert out.job_id == "nyc-001-backend"


def test_mock_stable_for_same_job(monkeypatch):
    monkeypatch.setattr(settings, "apply_mode", "mock")
    monkeypatch.setattr(settings, "mock_apply_determinism", 10)
    a = _run_mock_apply(_dispatch("stable-job-id")).status
    b = _run_mock_apply(_dispatch("stable-job-id")).status
    assert a == b


def test_apply_outcome_validation():
    raw = {
        "candidate_id": "x",
        "job_id": "y",
        "ats": "unknown",
        "status": "submitted",
        "message": "",
        "tokens_spent": 0,
        "wallclock_ms": 1,
    }
    ApplyOutcome.model_validate(raw)

