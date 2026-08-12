from __future__ import annotations

import logging
import os
import socket
import threading

import uvicorn

from .main import app


def main() -> None:
    """Run one web process and one durable worker against the same persistent SQLite volume."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stop = threading.Event()
    worker_token = f"{socket.gethostname()}:{os.getpid()}:cloud"

    def worker_loop() -> None:
        while not stop.is_set():
            result = app.state.pipeline.run_once(worker_token)
            if result is None:
                stop.wait(app.state.settings.worker_poll_seconds)

    worker = threading.Thread(target=worker_loop, name="alpha-cloud-worker", daemon=True)
    worker.start()
    try:
        uvicorn.run(
            app,
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
        )
    finally:
        stop.set()
        worker.join(timeout=5)


if __name__ == "__main__":
    main()
