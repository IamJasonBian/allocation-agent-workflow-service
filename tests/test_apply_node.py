"""`_run_node_agent` path (subprocess contract) — no real Node."""

import subprocess
from unittest.mock import MagicMock

import pytest

from allocation_agent.schemas import AgentDispatch, JobCandidate
from allocation_agent.tasks import apply as apply_mod


def _dispatch() -> AgentDispatch:
    job = JobCandidate(
        job_id="j1",
        company_id="c",
        ats="greenhouse",
        title="Engineer",
        apply_url="https://example.com/j",
        posted_at=0,
        expected_callback_prob=0.5,
    )
    return AgentDispatch(candidate_id="u1", job=job, reason="test")


def test_node_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="node", timeout=1)

    monkeypatch.setattr(apply_mod.subprocess, "run", boom)
    out = apply_mod._run_node_agent(_dispatch())
    assert out.status == "error"
    assert "timed out" in out.message.lower()


def test_node_empty_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apply_mod.subprocess,
        "run",
        MagicMock(return_value=MagicMock(stdout="", stderr="oops", returncode=0)),
    )
    out = apply_mod._run_node_agent(_dispatch())
    assert out.status == "error"
    assert "empty" in out.message.lower()


def test_node_non_json_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apply_mod.subprocess,
        "run",
        MagicMock(return_value=MagicMock(stdout="not json\n", stderr="", returncode=0)),
    )
    out = apply_mod._run_node_agent(_dispatch())
    assert out.status == "error"
    assert "non-json" in out.message.lower()


def test_node_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    line = '{"status":"submitted","message":"ok","tokens_spent":0,"wallclock_ms":1}\n'
    monkeypatch.setattr(
        apply_mod.subprocess,
        "run",
        MagicMock(return_value=MagicMock(stdout=line, stderr="", returncode=0)),
    )
    out = apply_mod._run_node_agent(_dispatch())
    assert out.status == "submitted"
    assert out.message == "ok"
