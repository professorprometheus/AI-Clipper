from __future__ import annotations

import argparse
import logging
import os
import socket
import time

from .config import Settings
from .db import Database
from .pipeline import Pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the durable ALPHA worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="process at most one checkpointed stage, then exit (for scheduled compute)",
    )
    parser.add_argument(
        "--max-stages",
        type=int,
        default=0,
        help="process up to this many stages, then exit; zero keeps polling",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_env()
    pipeline = Pipeline(Database(settings.database_target, settings.migrations_path), settings)
    token = f"{socket.gethostname()}:{os.getpid()}"
    completed = 0
    while True:
        result = pipeline.run_once(token)
        if result is not None:
            completed += 1
        if args.once or (args.max_stages > 0 and completed >= args.max_stages):
            return
        if result is None:
            if args.max_stages > 0:
                return
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
