"""Structured timing logs — name + ms only, never payloads."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger("timing")


@contextmanager
def timed(name: str) -> Iterator[dict]:
    info: dict = {"name": name, "ms": None, "ok": True, "error": None}
    t0 = time.perf_counter()
    try:
        yield info
    except Exception as e:  # noqa: BLE001
        info["ok"] = False
        info["error"] = type(e).__name__
        raise
    finally:
        info["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        if info["ok"]:
            log.info("gpu_call name=%s ms=%.1f", name, info["ms"])
        else:
            log.warning("gpu_call name=%s ms=%.1f error=%s", name, info["ms"], info["error"])
