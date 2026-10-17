"""Application settings, loaded from the repository-root .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- OpenAI ----------------------------------------------------------
    openai_api_key: str = ""
    # Any OpenAI-compatible endpoint works (Azure, a proxy, a local server).
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # Rate limits are per minute, so a six-stage run can trip them. Retries
    # back off rather than failing the run.
    llm_max_retries: int = 5

    # --- Slack -----------------------------------------------------------
    slack_bot_token: str = ""
    slack_app_token: str = ""

    # --- ClickUp ---------------------------------------------------------
    clickup_api_token: str = ""
    # The Space project folders are created in (app.clickup.com/<team>/v/s/<id>).
    clickup_space_id: str = ""
    # Set false to build the work breakdown without publishing it to ClickUp.
    # The task graph is still produced and shown; only the push is skipped.
    # Opt-out rather than automatic, so a missing token is still reported as
    # the misconfiguration it usually is.
    clickup_enabled: bool = True
    # The monitor re-reads published ClickUp projects and logs deviations from
    # the plan. The free plan allows 100 requests a minute; minimum 30s.
    monitor_enabled: bool = True
    monitor_interval_seconds: int = 300

    # --- GitHub ----------------------------------------------------------
    github_token: str = ""
    github_owner: str = ""

    # --- Vercel ----------------------------------------------------------
    vercel_token: str = ""
    vercel_team_id: str = ""

    # --- Application -----------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # Off by default: the API listens on localhost, where a password would only
    # be a password to lose. Turn it on before putting the dashboard on a domain.
    dashboard_auth: bool = False
    # Optional: creates (and keeps in sync) an "admin" login in users.json.
    # Other logins are added with `make create-user`.
    dashboard_password: str = "changeme"
    # Signs dashboard login tokens. Unset: a random per-process secret, so
    # every login ends when the backend restarts.
    session_secret: str = ""
    # The only file the backend persists: dashboard logins, with passwords
    # stored as salted hashes. Pipeline state is never written here.
    users_file: Path = REPO_ROOT / "users.json"
    # Demo convenience: load the canned conversation from scripts/seed.py into
    # this channel at startup, so `/pm start` there has something to read.
    seed_channel: str = ""
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
