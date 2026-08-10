from __future__ import annotations

import logging
import os
import socket
import time

from .config import Settings
from .db import Database
from .pipeline import Pipeline


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_env()
    pipeline = Pipeline(Database(settings.database_path, settings.migrations_path), settings)
    token = f"{socket.gethostname()}:{os.getpid()}"
    while True:
        result = pipeline.run_once(token)
        if result is None:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
