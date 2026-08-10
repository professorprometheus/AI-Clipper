from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe ALPHA backup and retention operations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--destination", type=Path)
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--older-than-days", type=int, default=30)
    cleanup.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "backup":
        destination = (
            args.destination or Path("backups") / f"alpha-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"
        )
        print(backup_database(settings.database_path, destination))
    else:
        targets = cleanup_intermediates(
            settings.storage_path, max(1, args.older_than_days), apply=args.apply
        )
        action = "removed" if args.apply else "would remove"
        print(f"{action} {len(targets)} generated intermediate(s)")


if __name__ == "__main__":
    main()
