"""
End-to-end: real finder-mock subprocess + ``CrawlerSource`` / ``load_candidates``.

Requires sibling checkout ``../finder-mock`` and ``RUN_FINDER_E2E=1``:

  cd allocation-agent
  RUN_FINDER_E2E=1 .venv/bin/pytest tests/test_integration_allocation_finder_e2e.py -v
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Generator

import httpx
import pytest

from allocation_agent.schemas import JobCandidate
from allocation_agent.sources import CrawlerSource, load_candidates

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("RUN_FINDER_E2E"),
        reason="set RUN_FINDER_E2E=1; starts finder-mock (subprocess) + real HTTP",
    ),
]


def _gamma_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _finder_checkout() -> Path:
    p = _gamma_root() / "finder-mock"
    if not p.is_dir():
        pytest.skip("finder-mock not found (expected at ../finder-mock from this repo root)")
    return p


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    _, p = s.getsockname()
    s.close()
    return int(p)


@pytest.fixture
def live_finder() -> Generator[dict[str, Any], None, None]:
    root = _finder_checkout()
    src = root / "src"
    assert src.is_dir()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PYTHONPATH": str(src)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "finder_service.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                r = httpx.get(f"{base}/health", timeout=0.5)
                if r.status_code == 200:
                    break
            except (httpx.HTTPError, OSError):
                if proc.poll() is not None:
                    pytest.fail("uvicorn for finder-mock exited early")
            time.sleep(0.1)
        else:
            proc.terminate()
            pytest.fail("finder-mock /health not ready in time")
        # Conservative seed: example.com (robots 404 → allow)
        httpx.post(
            f"{base}/v1/seed",
            json={"url": "https://example.com/alloc-e2e", "depth": 0},
            timeout=10.0,
        ).raise_for_status()
        t0 = time.monotonic() + 4.0
        while time.monotonic() < t0:
            j = httpx.get(f"{base}/v1/jobs", params={"limit": 5}, timeout=2.0).json()
            jobs = j.get("jobs") or []
            if any("example.com" in str(x.get("apply_url", "")) for x in jobs):
                break
            time.sleep(0.1)
        else:
            assert False, "no job in buffer after seed"  # noqa: S101
        yield {"base": base, "port": port}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_crawlersource_e2e_http_jobs(live_finder: dict[str, Any]) -> None:
    base: str = live_finder["base"]
    src = CrawlerSource(
        base_url=base,
        use_http=True,
    )
    jobs = [j for j in src.iter_candidates() if "example.com" in j.apply_url]
    assert len(jobs) >= 1
    assert all(isinstance(x, JobCandidate) for x in jobs)


def test_load_candidates_merges_crawler_e2e(live_finder: dict[str, Any]) -> None:
    base: str = live_finder["base"]
    crawler = CrawlerSource(
        base_url=base,
        use_http=True,
    )
    from allocation_agent.sources.dover import DoverSource

    merged = load_candidates(
        [
            DoverSource(),
            crawler,
        ]
    )
    assert isinstance(merged, list) and len(merged) >= 1
    assert all(isinstance(c, JobCandidate) for c in merged)
