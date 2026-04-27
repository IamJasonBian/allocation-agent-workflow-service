"""Shared types for slug discovery sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Protocol, runtime_checkable


@dataclass
class SlugCandidate:
    slug: str
    company: str
    ats: str  # "greenhouse" | "lever" | "ashby"
    source: str
    career_page_url: str = ""


@runtime_checkable
class SlugSource(Protocol):
    name: str

    def iter_candidates(self) -> Iterator[SlugCandidate]: ...
