import structlog

from ..celery_app import app
from ..schemas import AgentDispatch
from ..sources import load_candidates
from ..stores.feedback import ensure_applications, pick_work
from .apply import apply_to_job

log = structlog.get_logger()


@app.task(name="allocation_agent.tasks.select.tick")
def tick(candidate_id: str, queue_size: int = 5) -> int:
    """Selector: load all enabled sources, dedupe + score, dispatch top-N to apply.

    Flow:
      1. Pull ranked candidates from every enabled source.
      2. Upsert them into the `applications` ledger as `eligible` (idempotent).
      3. Atomically transition top-N to `in_flight` with a lease, preserving rank.
      4. Enqueue an `apply` task for each picked row.

    Phase 2 swaps the scoring for the LLM/DeepFM rankers and adds MMR + cooldowns.
    """
    candidates = load_candidates()
    ensure_applications(candidate_id, candidates)

    preferred = [c.job_id for c in candidates[: queue_size * 3]]   # buffer for skipped states
    picked = pick_work(
        candidate_id=candidate_id,
        limit=queue_size,
        preferred_job_ids=preferred,
    )

    by_id = {c.job_id: c for c in candidates}
    dispatched = 0
    for _, job_id in picked:
        job = by_id.get(job_id)
        if job is None:
            # Crash-recovered row whose source no longer lists the job. Skip.
            log.warning(
                "select.pick_without_source",
                candidate=candidate_id,
                job=job_id,
            )
            continue
        dispatch = AgentDispatch(
            candidate_id=candidate_id,
            job=job,
            reason=f"ledger pick p_cb={job.expected_callback_prob:.3f}",
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
        dispatched += 1

    return dispatched
