from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


ATS = Literal["greenhouse", "lever", "ashby", "workday", "workable", "icims", "unknown"]
OutcomeStatus = Literal[
    "submitted",
    "blocked",
    "captcha",
    "error",
    "skipped",
    "needs_auth",
    "interrupted",
]


class JobCandidate(BaseModel):
    job_id: str
    company_id: str
    ats: ATS
    title: str
    apply_url: str
    posted_at: int
    expected_callback_prob: float = 0.0


class AgentDispatch(BaseModel):
    candidate_id: str
    job: JobCandidate
    dispatched_at: datetime = Field(default_factory=datetime.utcnow)
    reason: str = ""


class ApplyOutcome(BaseModel):
    candidate_id: str
    job_id: str
    ats: ATS
    status: OutcomeStatus
    message: str = ""
    tokens_spent: int = 0
    wallclock_ms: int = 0
    finished_at: datetime = Field(default_factory=datetime.utcnow)


class CallbackSignal(BaseModel):
    candidate_id: str
    job_id: str
    kind: Literal["callback", "screener", "rejection", "offer"]
    received_at: datetime = Field(default_factory=datetime.utcnow)
    raw: Optional[str] = None
