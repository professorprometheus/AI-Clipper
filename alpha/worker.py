from __future__ import annotations

import argparse
import logging
import os
import socket
import time

from .config import Settings
from .db import Database
from .pipeline import Pipeline

logger = logging.getLogger(__name__)


def _is_terminal_failure(result: dict | None) -> bool:
    return bool(result and result.get("status") == "failed")


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
        if _is_terminal_failure(result):
            logger.error(
                "ALPHA worker stopped after a terminal failure in stage %s.",
                result.get("stage", "unknown"),
            )
            raise SystemExit(1)
        if args.once or (args.max_stages > 0 and completed >= args.max_stages):
            logger.info(
                "ALPHA worker completed %s checkpointed stage invocation(s); stage limit reached.",
                completed,
            )
            return
        if result is None:
            if args.max_stages > 0:
                logger.info(
                    "ALPHA worker completed %s checkpointed stage invocation(s); no runnable work remains.",
                    completed,
                )
                return
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
