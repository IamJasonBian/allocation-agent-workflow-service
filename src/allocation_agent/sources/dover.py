"""Loader + filter for Dover-shaped job listings (JSON array on disk)."""

import json
from pathlib import Path
from typing import Iterable

from ..config import settings
from ..schemas import JobCandidate


INCLUDE_KEYWORDS = [
    "software", "engineer", "developer", "data", "machine learning", "ml ",
    "backend", "back-end", "full stack", "full-stack", "fullstack",
    "infrastructure", "platform", "devops", "sre", "reliability",
    "quantitative", "quant", "analyst", "scientist",
    "python", "java", "cloud", "systems",
    "founding", "frontend", "front-end", "mobile", "ios", "android",
    "architect", "tech lead", "technical lead", "head of engineering",
    "ai ", "robotics", "automation", "security", "cyber",
    "product engineer", "implementation engineer",
]

EXCLUDE_KEYWORDS = [
    "intern", "recruiter", "recruiting", "human resources",
    "sales", "marketing", "design", "product manager",
    "account manager", "account executive", "partnership manager",
    "clinical", "nurse", "medical", "pharmacist",
    "customer success", "customer support",
    "executive assistant", "office manager",
    "content", "copywriter", "pr ", "public relations",
    "legal", "paralegal", "attorney", "counsel",
    "accountant", "bookkeeper", "controller", "compliance",
    "solutions consultant", "gtm", "treasury", "fp&a",
    "staff", "principal", "director", "head of", "vp ",
]

NON_US_LOCATIONS = [
    "international", "brazil", "europe", "india", "nigeria", "australia",
    "london", "uk", "berlin", "germany", "toronto", "canada",
    "singapore", "hong kong", "japan", "korea", "south africa", "africa",
    "remote (international", "latin america", "latam", "mexico",
    "philippines", "pakistan", "bangladesh", "vietnam",
    "tel aviv", "israel", "dubai", "lithuania", "spain", "romania",
    "portugal", "poland", "armenia", "taiwan", "china", "france", "paris",
    "netherlands", "amsterdam", "ireland", "dublin",
    "sweden", "stockholm", "denmark", "norway", "finland",
    "switzerland", "zurich", "austria", "vienna",
    "czech", "prague", "hungary", "budapest",
    "argentina", "buenos aires", "colombia", "bogota",
    "chile", "santiago", "peru", "lima",
]


def is_relevant(title: str, location: str = "") -> bool:
    t = (title or "").lower()
    l = (location or "").lower()
    if any(k in t for k in EXCLUDE_KEYWORDS):
        return False
    if not any(k in t for k in INCLUDE_KEYWORDS):
        return False
    if any(k in t or k in l for k in NON_US_LOCATIONS):
        return False
    return True


def score_priority(title: str) -> float:
    """Heuristic callback-prob for Senior + mid-level roles.

    Staff / principal / director are filtered out upstream; this function only
    decides the relative ordering of Senior and mid-level engineering titles.
    """
    t = title.lower()
    score = 0.5

    if "senior" in t or "sr. " in t or "sr " in t:
        score += 0.15
    elif not any(k in t for k in ("staff", "principal", "lead")):
        score += 0.12

    if "new york" in t or "nyc" in t:
        score += 0.15
    if "remote" in t and "international" not in t:
        score += 0.05
    if "founding" in t:
        score += 0.05

    return min(score, 1.0)


class DoverSource:
    """Dover-shaped JSON file on disk. One row per posting."""

    name = "dover"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.dover_jobs_path

    def iter_candidates(self) -> Iterable[JobCandidate]:
        for c in _read_and_map(self.path):
            yield c


def _read_and_map(path: Path) -> list[JobCandidate]:
    raw = json.loads(path.read_text())
    out: list[JobCandidate] = []
    for r in raw:
        title = r.get("title", "")
        loc = r.get("locations") or ""
        if not is_relevant(title, loc):
            continue
        out.append(
            JobCandidate(
                job_id=r["jobId"],
                company_id=r.get("companySlug") or r.get("company", "unknown"),
                ats="unknown",
                title=title,
                apply_url=r["url"],
                posted_at=0,
                expected_callback_prob=score_priority(title),
            )
        )
    out.sort(key=lambda j: j.expected_callback_prob, reverse=True)
    return out


def load_dover_candidates(path: Path | None = None) -> list[JobCandidate]:
    """Backwards-compatible shim. Prefer `load_candidates()` from `..sources`."""
    return _read_and_map(path or settings.dover_jobs_path)
