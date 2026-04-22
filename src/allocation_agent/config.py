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
    """Which job sources `load_candidates()` pulls from. Registry in `sources/__init__.py`."""
    enabled_sources: list[str] = Field(default_factory=lambda: ["dover"])
    """`mock` skips Node/Puppeteer (tests, dry runs). `node` runs `node_agent/apply.mjs`."""
    apply_mode: str = "mock"
    """Deterministic mock outcomes when `apply_mode=mock` (0–99)."""
    mock_apply_determinism: int = Field(default=73, ge=0, le=99)
    """`none` = no isolation. `mac_os_space` = require a dedicated macOS Space; abort on focus loss."""
    isolation_mode: Literal["none", "mac_os_space"] = "none"
    """Seconds the Chrome tab may be hidden before the runner aborts with `interrupted`."""
    isolation_focus_loss_grace_s: float = Field(default=3.0, ge=0.5)


settings = Settings()
