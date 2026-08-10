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

    @classmethod
    def from_env(cls) -> Settings:
        root = Path(__file__).resolve().parent.parent
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
        )
