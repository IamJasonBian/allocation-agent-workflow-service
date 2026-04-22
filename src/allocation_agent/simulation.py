"""In-process pipeline runs (no Redis) for demos and integration tests."""

from __future__ import annotations

from typing import Any

from .schemas import AgentDispatch
from .sources.dover import load_dover_candidates
from .stores.feedback import record_outcome
from .tasks.apply import execute_apply


def run_simulation(
    candidate_id: str,
    queue_size: int = 5,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Load Dover feed, take top `queue_size` jobs, apply with current `apply_mode`, optionally persist."""
    ranked = load_dover_candidates()[:queue_size]
    outcomes: list[dict[str, Any]] = []
    for job in ranked:
        dispatch = AgentDispatch(
            candidate_id=candidate_id,
            job=job,
            reason="nyc machine-spray simulation",
        )
        outcome = execute_apply(dispatch)
        if persist:
            record_outcome(outcome)
        outcomes.append(outcome.model_dump(mode="json"))
    return {
        "candidate_id": candidate_id,
        "jobs_considered": len(ranked),
        "outcomes": outcomes,
    }
