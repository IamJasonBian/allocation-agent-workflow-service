import random

import structlog

from ..celery_app import app
from ..schemas import AgentDispatch
from ..sources import load_candidates
from ..stores.feedback import (
    ensure_applications,
    pick_work,
    reclaim_expired_leases,
)
from .apply import apply_to_job

log = structlog.get_logger()


@app.task(name="allocation_agent.tasks.select.reclaim_leases")
def reclaim_leases(candidate_id: str | None = None) -> int:
    """Beat-scheduled proactive lease reclaimer.

    Crash-safety is already covered lazily by `pick_work`; this task makes
    reclamation happen on a fixed cadence so stuck rows don't have to wait
    for the next selector tick.
    """
    n = reclaim_expired_leases(candidate_id)
    if n:
        log.info("reclaimed_expired_leases", count=n, candidate=candidate_id or "*")
    return n


@app.task(name="allocation_agent.tasks.select.tick")
def tick(
    candidate_id: str,
    queue_size: int = 5,
    *,
    random_sample: bool = False,
    seed: int | None = None,
) -> int:
    """Selector: load all enabled sources, dedupe + score, dispatch top-N to apply.

    Flow:
      1. Pull ranked candidates from every enabled source.
      2. Upsert them into the `applications` ledger as `eligible` (idempotent).
      3. Build a preference list for `pick_work`:
         - Production (default): top-N by `expected_callback_prob`
         - Testing (`random_sample=True`): a random sample of the eligible
           pool — ensures each live-testing run hits a different URL / ATS
           slice and doesn't hammer the same 3 top-ranked companies.
      4. Atomically transition up to `queue_size` rows to `in_flight`.
      5. Enqueue an `apply` task for each picked row.

    `seed` makes random sampling reproducible for regression tests.
    """
    candidates = load_candidates()
    ensure_applications(candidate_id, candidates)

    pool = list(candidates)
    if random_sample:
        rng = random.Random(seed)
        rng.shuffle(pool)
        reason_prefix = "random-sample"
    else:
        reason_prefix = "ledger pick"

    # Buffer 3x the queue_size into the preference list so rows blocked by
    # state (done/backoff/in_flight) don't starve the dispatch.
    preferred = [c.job_id for c in pool[: queue_size * 3]]
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
            reason=f"{reason_prefix} p_cb={job.expected_callback_prob:.3f}",
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
            mode=reason_prefix,
        )
        dispatched += 1

    return dispatched
