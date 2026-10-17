"""Live status of every sponsor tool the app uses. Cheap health checks, 2 s timeouts."""
from __future__ import annotations

import asyncio

import aiohttp

from config import settings
from sponsors import vast_store

T = aiohttp.ClientTimeout(total=2)


def _auth() -> dict:
    return {"Authorization": f"Bearer {settings.gpu_token}"} if settings.gpu_token else {}


async def _get(http, url: str, headers: dict | None = None, ok_codes=(200,)) -> tuple[bool, str]:
    try:
        async with http.get(url, headers=headers or {}, timeout=T) as r:
            return r.status in ok_codes, f"HTTP {r.status}"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


async def _vss(http) -> tuple[bool, str]:
    if not settings.vss_ready:
        return False, "VSS not configured"
    return await _get(http, settings.vss_url + "/health", ok_codes=(200, 401, 404))


async def _wandb(http) -> tuple[bool, str]:
    if not settings.wandb_ready:
        return False, "W&B creds not configured"
    return await _get(http, settings.wandb_base + "/models", {"Authorization": f"Bearer {settings.wandb_key}"},
                      ok_codes=(200, 401, 403))  # reachable; auth validated on real calls


def _static(ok: bool, detail: str):
    async def f(_http):
        return ok, detail
    return f


# id, sponsor, name, role, checker
def _specs():
    a = _auth()
    return [
        ("cosmos3", "NVIDIA", "Cosmos3-Reason", "VLM: frame -> twin JSON, mistake diagnosis",
         lambda h: _get(h, settings.cosmos_url + "/v1/health/ready", a)),
        ("yolo11", "NVIDIA", "YOLO11", "Change trigger and scene gate",
         lambda h: _get(h, settings.yolo_url + "/healthz", a)),
        ("canary", "NVIDIA", "Canary-1B", "Hold-to-talk speech recognition",
         lambda h: _get(h, settings.canary_url + "/v1/health/ready", a)),
        ("embed1", "NVIDIA", "Cosmos-Embed1", "Mistake memory: embed + cosine recall",
         lambda h: _get(h, settings.embed_url + "/v1/health/ready", a)),
        ("wandb", "Weights & Biases", "W&B Inference", "LLM phrasing of verified guidance", _wandb),
        ("vast_s3", "VAST Data", "VAST S3", "Session twin snapshots, key frames, summary",
         lambda h: vast_store.check_s3()),
        ("vast_vss", "VAST Data", "VAST DB / VSS", "Search over indexed past builds", _vss),
        ("coreweave", "CoreWeave", "CoreWeave GPU", "Hosts the NVIDIA model endpoints",
         lambda h: _get(h, settings.cosmos_url + "/v1/models", a)),
        ("cursor", "Cursor", "Cursor", "Coding agent that built this app", _static(True, "build-time tool")),
    ]


async def sponsor_status(http) -> dict:
    specs = _specs()

    async def run(spec):
        try:
            ok, detail = await asyncio.wait_for(spec[4](http), 3)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, type(e).__name__
        return {"id": spec[0], "sponsor": spec[1], "name": spec[2], "role": spec[3],
                "ok": bool(ok), "detail": detail}

    items = await asyncio.gather(*(run(s) for s in specs))
    return {"tools": items, "ok_count": sum(i["ok"] for i in items), "total": len(items)}
