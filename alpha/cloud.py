from __future__ import annotations

import logging
import os
import socket
import threading

import uvicorn

from .main import app


def main() -> None:
    """Run the stateless web app, optionally with an opportunistic worker."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stop = threading.Event()
    worker_token = f"{socket.gethostname()}:{os.getpid()}:cloud"

    def worker_loop() -> None:
        while not stop.is_set():
            result = app.state.pipeline.run_once(worker_token)
            if result is None:
                stop.wait(app.state.settings.worker_poll_seconds)

    worker = None
    if app.state.settings.run_embedded_worker:
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
        if worker:
            worker.join(timeout=5)


if __name__ == "__main__":
    main()
