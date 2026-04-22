from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    """Base URL: finder-mock or future crawler read API (see `CrawlerSource._fetch_http`)."""
    crawler_base_url: str = "http://127.0.0.1:8765"
    """When True, `CrawlerSource` calls GET `{crawler_base_url}/v1/jobs` (e.g. finder-mock). When False, uses in-process mock list."""
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
