import structlog

from ..celery_app import app
from ..schemas import ApplyOutcome, CallbackSignal
from ..stores.feedback import (
    record_callback,
    record_outcome,
    transition_on_outcome,
)

log = structlog.get_logger()


@app.task(name="allocation_agent.tasks.feedback.record_outcome_task")
def record_outcome_task(outcome_payload: dict) -> int:
    """Append the outcome to the event log AND transition the applications ledger.

    Both writes happen sequentially. The event log is append-only (source of
    truth for audit + training). The ledger is the current-state projection the
    selector reads on the next tick.
    """
    outcome = ApplyOutcome.model_validate(outcome_payload)
    row_id = record_outcome(outcome)
    new_state = transition_on_outcome(outcome)
    log.info(
        "feedback.outcome",
        row=row_id,
        candidate=outcome.candidate_id,
        job=outcome.job_id,
        status=outcome.status,
        ledger_state=new_state,
    )
    return row_id


@app.task(name="allocation_agent.tasks.feedback.record_callback_task")
def record_callback_task(signal_payload: dict) -> int:
    """Callbacks are training signals, not state transitions. Append to the log only.

    The ledger row for this (candidate, job) is already terminal (`done`) if we
    applied; callbacks never flip it back.
    """
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
