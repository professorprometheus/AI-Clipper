from __future__ import annotations

import threading
import time

import uvicorn

from .main import app


def worker_loop() -> None:
    pipeline = app.state.pipeline
    while True:
        result = pipeline.run_once("dev-background-worker")
        if result is None:
            time.sleep(app.state.settings.worker_poll_seconds)


def main() -> None:
    threading.Thread(target=worker_loop, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
