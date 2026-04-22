from typing import Iterable, Protocol, runtime_checkable

from ..schemas import JobCandidate


@runtime_checkable
class JobSource(Protocol):
    """A producer of JobCandidates.

    Implementations own their own filtering, normalization, and scoring so the
    loader can treat every source uniformly. Dedupe across sources happens at
    the loader level on `(company_id, job_id)`.
    """

    name: str

    def iter_candidates(self) -> Iterable[JobCandidate]: ...
