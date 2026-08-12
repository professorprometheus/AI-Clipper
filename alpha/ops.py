from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings
from .db import Database
from .providers import LocalStorageAdapter, Renderer


def backup_database(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    return destination


def cleanup_intermediates(storage: Path, older_than_days: int, apply: bool = False) -> list[Path]:
    """Find/delete only generated render intermediates; final clips and user uploads are retained."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    targets: list[Path] = []
    render_root = (storage / "renders").resolve()
    if not render_root.exists():
        return targets
    for path in render_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".ppm", ".render.json"}:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if modified < cutoff and render_root in path.resolve().parents:
            targets.append(path)
    if apply:
        for path in targets:
            path.unlink()
    return targets


def deployment_diagnostics(settings: Settings) -> dict:
    checks: dict[str, dict] = {}
    try:
        database = Database(settings.database_path, settings.migrations_path)
        migration_count = database.one("SELECT COUNT(*) AS n FROM schema_migrations")["n"]
        checks["database"] = {"ok": migration_count > 0, "migrations": migration_count}
    except Exception as exc:
        checks["database"] = {"ok": False, "error_class": type(exc).__name__}
    try:
        storage = LocalStorageAdapter(settings.storage_path)
        probe_path = Path(storage.put_bytes("operations/write-probe", b"alpha"))
        probe_path.unlink()
        checks["storage"] = {"ok": True, "path": str(settings.storage_path.resolve())}
    except Exception as exc:
        checks["storage"] = {"ok": False, "error_class": type(exc).__name__}
    renderer = Renderer(LocalStorageAdapter(settings.storage_path))
    checks["ffmpeg"] = {"ok": bool(renderer._ffmpeg())}
    auth_configured = bool(settings.admin_email and settings.admin_password)
    checks["authentication"] = {
        "ok": not settings.require_auth or auth_configured,
        "required": settings.require_auth,
        "credentials_configured": auth_configured,
        "secure_cookie": settings.cookie_secure,
    }
    email_provider_valid = settings.email_provider in {"file", "resend"}
    resend_configured = bool(settings.resend_api_key and settings.resend_from_email)
    checks["email"] = {
        "ok": email_provider_valid and (settings.email_provider != "resend" or resend_configured),
        "provider": settings.email_provider,
        "api_key_configured": bool(settings.resend_api_key),
        "from_address_configured": bool(settings.resend_from_email),
    }
    live_mode = settings.provider_mode == "live"
    checks["live_providers"] = {
        "ok": not live_mode or bool(settings.youtube_api_key),
        "mode": settings.provider_mode,
        "youtube_api_key_configured": bool(settings.youtube_api_key),
        "youtube_caption_oauth_configured": bool(
            settings.youtube_oauth_access_token
            or (
                settings.youtube_oauth_client_id
                and settings.youtube_oauth_client_secret
                and settings.youtube_oauth_refresh_token
            )
        ),
        "tiktok_research_access_configured": bool(
            settings.tiktok_research_access_token
            or (settings.tiktok_client_key and settings.tiktok_client_secret)
        ),
        "instagram_research_access_configured": bool(
            settings.instagram_access_token and settings.instagram_user_id
        ),
    }
    return {"ok": all(check["ok"] for check in checks.values()), "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe ALPHA backup and retention operations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--destination", type=Path)
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--older-than-days", type=int, default=30)
    cleanup.add_argument("--apply", action="store_true")
    subparsers.add_parser("doctor")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "backup":
        destination = (
            args.destination or Path("backups") / f"alpha-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
        )
        print(backup_database(settings.database_path, destination))
    elif args.command == "cleanup":
        targets = cleanup_intermediates(
            settings.storage_path, max(1, args.older_than_days), apply=args.apply
        )
        action = "removed" if args.apply else "would remove"
        print(f"{action} {len(targets)} generated intermediate(s)")
    else:
        result = deployment_diagnostics(settings)
        print(json.dumps(result, indent=2, sort_keys=True))
        if not result["ok"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
