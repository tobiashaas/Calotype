"""Worker heartbeat — writes a timestamp file so Docker HEALTHCHECK can detect stalled workers.

Usage in worker main():
    from calotype_observability.heartbeat import start_heartbeat_thread
    start_heartbeat_thread("/tmp/lr_ff_feature_worker.heartbeat")

Docker HEALTHCHECK:
    HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
        CMD test $(( $(date +%s) - $(cat /tmp/lr_ff_<worker>.heartbeat) )) -lt 60
"""

from __future__ import annotations

import os
import threading
import time


def write_heartbeat(path: str) -> None:
    """Write current Unix timestamp (integer) to path."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(int(time.time())))
    os.replace(tmp, path)  # atomic rename


def start_heartbeat_thread(path: str, interval_seconds: int = 15) -> threading.Thread:
    """Start a daemon thread that writes a heartbeat file every `interval_seconds`."""

    def _loop() -> None:
        while True:
            try:
                write_heartbeat(path)
            except Exception:
                pass  # never crash the worker due to heartbeat failure
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name=f"heartbeat-{os.path.basename(path)}")
    t.start()
    return t
