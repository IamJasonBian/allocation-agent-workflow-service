import structlog

from ..celery_app import app
from ..schemas import ApplyOutcome, CallbackSignal
from ..stores.feedback import record_callback, record_outcome

log = structlog.get_logger()


@app.task(name="allocation_agent.tasks.feedback.record_outcome_task")
def record_outcome_task(outcome_payload: dict) -> int:
    outcome = ApplyOutcome.model_validate(outcome_payload)
    row_id = record_outcome(outcome)
    log.info(
        "feedback.outcome",
        row=row_id,
        candidate=outcome.candidate_id,
        job=outcome.job_id,
        status=outcome.status,
    )
    return row_id


@app.task(name="allocation_agent.tasks.feedback.record_callback_task")
def record_callback_task(signal_payload: dict) -> int:
    signal = CallbackSignal.model_validate(signal_payload)
    row_id = record_callback(signal)
    log.info(
        "feedback.callback",
        row=row_id,
        candidate=signal.candidate_id,
        job=signal.job_id,
        kind=signal.kind,
    )
    return row_id
