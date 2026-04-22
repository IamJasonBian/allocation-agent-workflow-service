import json
import os
import subprocess
import time
from pathlib import Path

import structlog
from celery import Task

from ..celery_app import app
from ..config import settings
from ..schemas import AgentDispatch, ApplyOutcome

log = structlog.get_logger()


def _run_mock_apply(dispatch: AgentDispatch) -> ApplyOutcome:
    """Deterministic outcomes for staging/tests (no browser)."""
    import hashlib

    h = int(
        hashlib.sha256(dispatch.job.job_id.encode()).hexdigest()[:12],
        16,
    ) % 100
    tier = (h + settings.mock_apply_determinism) % 100
    if tier < 70:
        status = "submitted"
        message = "mock: simulated submit"
    elif tier < 85:
        status = "captcha"
        message = "mock: captcha interstitial"
    else:
        status = "error"
        message = "mock: simulated ATS failure"

    return ApplyOutcome(
        candidate_id=dispatch.candidate_id,
        job_id=dispatch.job.job_id,
        ats=dispatch.job.ats,
        status=status,
        message=message,
        tokens_spent=0,
    )


def execute_apply(dispatch: AgentDispatch) -> ApplyOutcome:
    """Single-job apply: mock or Node runner."""
    if settings.apply_mode == "mock":
        return _run_mock_apply(dispatch)
    return _run_node_agent(dispatch)


NODE_AGENT_DIR = Path(__file__).resolve().parents[3] / "node_agent"
NODE_APPLY_SCRIPT = NODE_AGENT_DIR / "apply.mjs"


class ApplyTask(Task):
    autoretry_for = (TimeoutError, ConnectionError)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 3


@app.task(
    bind=True,
    base=ApplyTask,
    name="allocation_agent.tasks.apply.apply_to_job",
    rate_limit=settings.apply_rate_limit,
)
def apply_to_job(self, dispatch_payload: dict) -> dict:
    """Runs the Puppeteer-based Node agent on a single job and persists the outcome.

    The Node runner at `node_agent/apply.mjs` owns browser automation; this task
    owns the queue envelope, timeouts, retry policy, and feedback emission.
    """
    t0 = time.perf_counter()
    dispatch = AgentDispatch.model_validate(dispatch_payload)

    log.info(
        "apply.start",
        candidate=dispatch.candidate_id,
        job=dispatch.job.job_id,
        ats=dispatch.job.ats,
    )

    outcome = execute_apply(dispatch)
    outcome.wallclock_ms = int((time.perf_counter() - t0) * 1000)

    from .feedback import record_outcome_task
    record_outcome_task.apply_async(
        args=[outcome.model_dump(mode="json")],
        queue="feedback",
    )

    log.info(
        "apply.done",
        candidate=outcome.candidate_id,
        job=outcome.job_id,
        status=outcome.status,
        ms=outcome.wallclock_ms,
    )
    return outcome.model_dump(mode="json")


def _run_node_agent(dispatch: AgentDispatch) -> ApplyOutcome:
    env = os.environ.copy()
    env.setdefault(
        "CANDIDATE_PROFILE_JSON",
        str(Path.home() / ".config/allocation-agent/candidate.json"),
    )
    env.setdefault("NODE_PATH", str(NODE_AGENT_DIR / "node_modules"))
    env["ISOLATION_MODE"] = settings.isolation_mode
    env["ISOLATION_FOCUS_LOSS_GRACE_S"] = str(settings.isolation_focus_loss_grace_s)

    payload = dispatch.model_dump(mode="json")

    try:
        proc = subprocess.run(
            ["node", str(NODE_APPLY_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            cwd=str(NODE_AGENT_DIR),
            timeout=540,
        )
    except subprocess.TimeoutExpired:
        return ApplyOutcome(
            candidate_id=dispatch.candidate_id,
            job_id=dispatch.job.job_id,
            ats=dispatch.job.ats,
            status="error",
            message="node agent timed out",
        )

    last_line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if not last_line:
        return ApplyOutcome(
            candidate_id=dispatch.candidate_id,
            job_id=dispatch.job.job_id,
            ats=dispatch.job.ats,
            status="error",
            message=f"empty stdout; stderr: {proc.stderr[:400]}",
        )

    try:
        data = json.loads(last_line)
    except json.JSONDecodeError:
        return ApplyOutcome(
            candidate_id=dispatch.candidate_id,
            job_id=dispatch.job.job_id,
            ats=dispatch.job.ats,
            status="error",
            message=f"non-json runner output: {last_line[:200]}",
        )

    data.setdefault("candidate_id", dispatch.candidate_id)
    data.setdefault("job_id", dispatch.job.job_id)
    data.setdefault("ats", dispatch.job.ats)
    return ApplyOutcome.model_validate(data)
