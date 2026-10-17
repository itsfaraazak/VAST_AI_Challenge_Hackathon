"""Behind-the-scenes trace events. Every model/tool call emits one span to the UI.

WS message shape (type="trace"):
  {type, id, stage, label, model, sponsor, status: start|ok|error|skip, ms, detail, t}
`sponsor` is one of: nvidia, coreweave, wandb, vast, cursor, local.
"""
from __future__ import annotations

import itertools
import time
from contextlib import asynccontextmanager

_ids = itertools.count(1)


async def emit(sess, stage: str, *, label: str = "", model: str = "", sponsor: str = "local",
               status: str = "ok", ms: float | None = None, detail: str = "", sid: int | None = None) -> int:
    sid = sid or next(_ids)
    await sess.broadcast({
        "type": "trace", "id": sid, "stage": stage, "label": label or stage, "model": model,
        "sponsor": sponsor, "status": status, "ms": None if ms is None else round(ms, 1),
        "detail": detail[:400], "t": time.time(),
    })
    return sid


@asynccontextmanager
async def span(sess, stage: str, *, label: str = "", model: str = "", sponsor: str = "local"):
    """async with span(sess, 'cosmos', model='cosmos3-reason', sponsor='nvidia') as s: ...; s['detail']='..'"""
    state = {"detail": "", "status": "ok"}
    sid = await emit(sess, stage, label=label, model=model, sponsor=sponsor, status="start")
    t0 = time.perf_counter()
    try:
        yield state
    except Exception as e:  # noqa: BLE001
        state["status"] = "error"
        state["detail"] = state["detail"] or f"{type(e).__name__}: {e}"
        raise
    finally:
        await emit(sess, stage, label=label, model=model, sponsor=sponsor, status=state["status"],
                   ms=(time.perf_counter() - t0) * 1000, detail=state["detail"], sid=sid)
