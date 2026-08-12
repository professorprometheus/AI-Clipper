from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    storage_path: Path
    email_sink_path: Path
    base_url: str
    provider_mode: str
    worker_poll_seconds: float
    lease_seconds: int
    migrations_path: Path
    web_path: Path
    retry_base_seconds: float = 1.0
    max_job_attempts: int = 5
    require_auth: bool = False
    admin_email: str = ""
    admin_password: str = ""
    session_hours: int = 12
    cookie_secure: bool = False
    email_provider: str = "file"
    resend_api_key: str = ""
    resend_from_email: str = ""
    email_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> Settings:
        root = Path(__file__).resolve().parent.parent
        resend_api_key = os.getenv("RESEND_API_KEY", "")
        configured_email_provider = os.getenv("ALPHA_EMAIL_PROVIDER", "auto").lower()
        email_provider = (
            "resend"
            if configured_email_provider == "auto" and resend_api_key
            else "file"
            if configured_email_provider == "auto"
            else configured_email_provider
        )
        return cls(
            database_path=Path(os.getenv("ALPHA_DATABASE_PATH", root / "data" / "alpha.db")),
            storage_path=Path(os.getenv("ALPHA_STORAGE_PATH", root / "data" / "storage")),
            email_sink_path=Path(os.getenv("ALPHA_EMAIL_SINK_PATH", root / "data" / "emails")),
            base_url=os.getenv("ALPHA_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            provider_mode=os.getenv("ALPHA_PROVIDER_MODE", "fixture"),
            worker_poll_seconds=float(os.getenv("ALPHA_WORKER_POLL_SECONDS", "1")),
            lease_seconds=int(os.getenv("ALPHA_LEASE_SECONDS", "30")),
            migrations_path=root / "migrations",
            web_path=root / "web",
            retry_base_seconds=float(os.getenv("ALPHA_RETRY_BASE_SECONDS", "1")),
            max_job_attempts=int(os.getenv("ALPHA_MAX_JOB_ATTEMPTS", "5")),
            require_auth=os.getenv("ALPHA_REQUIRE_AUTH", "false").lower() in {"1", "true", "yes"},
            admin_email=os.getenv("ALPHA_ADMIN_EMAIL", ""),
            admin_password=os.getenv("ALPHA_ADMIN_PASSWORD", ""),
            session_hours=int(os.getenv("ALPHA_SESSION_HOURS", "12")),
            cookie_secure=os.getenv("ALPHA_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
            email_provider=email_provider,
            resend_api_key=resend_api_key,
            resend_from_email=os.getenv("RESEND_FROM_EMAIL", ""),
            email_timeout_seconds=float(os.getenv("ALPHA_EMAIL_TIMEOUT_SECONDS", "10")),
        )
