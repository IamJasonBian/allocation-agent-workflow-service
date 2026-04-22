"""In-process pipeline runs (no Redis) for demos and integration tests."""

from __future__ import annotations

from typing import Any

from .schemas import AgentDispatch
from .sources import load_candidates
from .stores.feedback import (
    ensure_applications,
    pick_work,
    record_outcome,
    transition_on_outcome,
)
from .tasks.apply import execute_apply


def run_simulation(
    candidate_id: str,
    queue_size: int = 5,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Load all enabled sources, pick top-N via the applications ledger, apply (mock or node)."""
    candidates = load_candidates()
    if persist:
        ensure_applications(candidate_id, candidates)
        picked_pairs = pick_work(
            candidate_id=candidate_id,
            limit=queue_size,
            preferred_job_ids=[c.job_id for c in candidates[: queue_size * 3]],
        )
        picked_ids = [p[1] for p in picked_pairs]
    else:
        picked_ids = [c.job_id for c in candidates[:queue_size]]

    by_id = {c.job_id: c for c in candidates}
    outcomes: list[dict[str, Any]] = []
    for jid in picked_ids:
        job = by_id.get(jid)
        if job is None:
            continue
        dispatch = AgentDispatch(
            candidate_id=candidate_id,
            job=job,
            reason="nyc machine-spray simulation",
        )
        outcome = execute_apply(dispatch)
        if persist:
            record_outcome(outcome)
            transition_on_outcome(outcome)
        outcomes.append(outcome.model_dump(mode="json"))
    return {
        "candidate_id": candidate_id,
        "jobs_considered": len(picked_ids),
        "outcomes": outcomes,
    }
