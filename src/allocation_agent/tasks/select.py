import structlog

from ..celery_app import app
from ..schemas import AgentDispatch
from ..sources.dover import load_dover_candidates
from .apply import apply_to_job

log = structlog.get_logger()


@app.task(name="allocation_agent.tasks.select.tick")
def tick(candidate_id: str, queue_size: int = 5) -> int:
    """Selector: load Dover jobs, filter for relevance, dispatch top-N to apply.

    Phase 2 swaps the scoring for the LLM/DeepFM rankers and adds MMR + cooldowns.
    For now we use the same keyword filter + heuristic priority as v1.
    """
    candidates = load_dover_candidates()
    ranked = candidates[:queue_size]

    for job in ranked:
        dispatch = AgentDispatch(
            candidate_id=candidate_id,
            job=job,
            reason=f"dover heuristic p_cb={job.expected_callback_prob:.3f}",
        )
        apply_to_job.apply_async(
            args=[dispatch.model_dump(mode="json")],
            queue="apply",
        )
        log.info(
            "dispatched",
            candidate=candidate_id,
            job=job.job_id,
            company=job.company_id,
            title=job.title,
        )

    return len(ranked)
