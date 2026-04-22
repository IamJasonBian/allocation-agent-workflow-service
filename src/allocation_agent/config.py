from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CrawlerHttpBackend = Literal["finder", "allocation_crawler"]

_DEFAULT_DOVER = Path(__file__).resolve().parent / "fixtures" / "mock-dover-jobs.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    feedback_db_url: str = "sqlite:///./feedback.db"
    log_level: str = "INFO"
    apply_rate_limit: str = "30/m"
    """Path to Dover-shaped JSON array (job feed)."""
    dover_jobs_path: Path = Field(default=_DEFAULT_DOVER)
    """Which job sources `load_candidates()` uses. Env ``ENABLED_SOURCES`` is JSON, e.g. ``["dover","crawler"]``."""
    enabled_sources: list[str] = Field(default_factory=lambda: ["dover"])
    """API root. Examples: `http://127.0.0.1:8765` (finder-mock), or Netlify
    `https://allocation-crawler-service.netlify.app/api/crawler` (see `crawler_http_backend`)."""
    crawler_base_url: str = "http://127.0.0.1:8765"
    """`finder` → GET ``/v1/jobs`` (finder-mock). `allocation_crawler` → GET ``/jobs?status=…`` (Netlify service)."""
    crawler_http_backend: CrawlerHttpBackend = "finder"
    """When using ``allocation_crawler`` without ``crawler_alloc_board``, cap rows pulled (API may return full list)."""
    crawler_alloc_max_rows: int = Field(default=300, ge=1, le=10_000)
    """For ``allocation_crawler``: optional ``board`` id (e.g. ``figma``, ``coinbase``) to scope jobs. Empty = all boards then cap."""
    crawler_alloc_board: str = ""
    """When True, `CrawlerSource` calls the HTTP backend. When False, uses in-process mock list."""
    crawler_use_http: bool = False
    crawler_state_path: Path = Field(
        default_factory=lambda: Path.home() / ".cache/allocation-agent/crawler-hwm",
        description="High-water mark file for a future live crawler; unused for finder-mock today.",
    )
    """`mock` skips Node/Puppeteer (tests, dry runs). `node` runs `node_agent/apply.mjs`."""
    apply_mode: str = "mock"
    """Deterministic mock outcomes when `apply_mode=mock` (0–99)."""
    mock_apply_determinism: int = Field(default=73, ge=0, le=99)
    """`none` = no isolation. `mac_os_space` = require a dedicated macOS Space; abort on focus loss."""
    isolation_mode: Literal["none", "mac_os_space"] = "none"
    """Seconds the Chrome tab may be hidden before the runner aborts with `interrupted`."""
    isolation_focus_loss_grace_s: float = Field(default=3.0, ge=0.5)


settings = Settings()
