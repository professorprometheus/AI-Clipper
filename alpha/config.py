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
    youtube_api_key: str = ""
    youtube_oauth_access_token: str = ""
    youtube_oauth_client_id: str = ""
    youtube_oauth_client_secret: str = ""
    youtube_oauth_refresh_token: str = ""
    tiktok_research_access_token: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    instagram_access_token: str = ""
    instagram_user_id: str = ""
    research_region: str = "GB"
    research_lookback_days: int = 14
    research_results_per_query: int = 10
    database_url: str = ""
    storage_provider: str = "local"
    s3_endpoint_url: str = ""
    s3_region: str = "auto"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    run_embedded_worker: bool = True

    @property
    def database_target(self) -> str | Path:
        return self.database_url or self.database_path

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
            base_url=os.getenv(
                "ALPHA_BASE_URL",
                os.getenv("RENDER_EXTERNAL_URL", "http://127.0.0.1:8000"),
            ).rstrip("/"),
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
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
            youtube_oauth_access_token=os.getenv("YOUTUBE_OAUTH_ACCESS_TOKEN", ""),
            youtube_oauth_client_id=os.getenv("YOUTUBE_OAUTH_CLIENT_ID", ""),
            youtube_oauth_client_secret=os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET", ""),
            youtube_oauth_refresh_token=os.getenv("YOUTUBE_OAUTH_REFRESH_TOKEN", ""),
            tiktok_research_access_token=os.getenv("TIKTOK_RESEARCH_ACCESS_TOKEN", ""),
            tiktok_client_key=os.getenv("TIKTOK_CLIENT_KEY", ""),
            tiktok_client_secret=os.getenv("TIKTOK_CLIENT_SECRET", ""),
            instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN", ""),
            instagram_user_id=os.getenv("INSTAGRAM_USER_ID", ""),
            research_region=os.getenv("ALPHA_RESEARCH_REGION", "GB").upper(),
            research_lookback_days=max(
                1, min(30, int(os.getenv("ALPHA_RESEARCH_LOOKBACK_DAYS", "14")))
            ),
            research_results_per_query=max(
                1, min(50, int(os.getenv("ALPHA_RESEARCH_RESULTS_PER_QUERY", "10")))
            ),
            database_url=os.getenv("DATABASE_URL", ""),
            storage_provider=os.getenv("ALPHA_STORAGE_PROVIDER", "local").lower(),
            s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", ""),
            s3_region=os.getenv("S3_REGION", "auto"),
            s3_bucket=os.getenv("S3_BUCKET", ""),
            s3_access_key_id=os.getenv("S3_ACCESS_KEY_ID", ""),
            s3_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY", ""),
            run_embedded_worker=os.getenv("ALPHA_RUN_EMBEDDED_WORKER", "true").lower()
            in {"1", "true", "yes"},
        )
