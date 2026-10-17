"""'Have I made this mistake before?' memory using NVIDIA Cosmos-Embed1 (256-d text vectors)."""
from __future__ import annotations

import logging
import math

import aiohttp

from config import settings
from trace import span

log = logging.getLogger("embed_memory")

THRESHOLD = 0.82
_model_id: str | None = None


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if settings.gpu_token:
        h["Authorization"] = f"Bearer {settings.gpu_token}"
    return h


async def _model(http) -> str:
    global _model_id
    if settings.embed_model:
        return settings.embed_model
    if _model_id:
        return _model_id
    async with http.get(settings.embed_url + "/v1/models", headers=_headers(), timeout=aiohttp.ClientTimeout(total=5)) as r:
        _model_id = (await r.json())["data"][0]["id"]
    return _model_id


async def embed(http, text: str) -> list[float] | None:
    try:
        body = {"input": text[:500], "model": await _model(http), "request_type": "query",
                "encoding_format": "float"}
        async with http.post(settings.embed_url + "/v1/embeddings", json=body, headers=_headers(),
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status >= 400:
                return None
            return (await r.json())["data"][0]["embedding"]
    except Exception as e:  # noqa: BLE001
        log.warning("embed failed: %s", type(e).__name__)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _mem(sess) -> list[dict]:
    if not hasattr(sess, "_mistake_mem"):
        sess._mistake_mem = []
    return sess._mistake_mem


def _http(sess):
    return getattr(sess, "http", None)


async def _embed_traced(sess, http, text, label) -> list[float] | None:
    async with span(sess, "embed", label=label, model="cosmos-embed1", sponsor="nvidia") as s:
        v = await embed(http, text)
        if v is None:
            s["status"] = "error"
            s["detail"] = "embed unavailable"
        else:
            s["detail"] = f"dim={len(v)}"
        return v


async def remember(sess, text: str, http=None) -> bool:
    http = http or _http(sess)
    if http is None or not text:
        return False
    v = await _embed_traced(sess, http, text, "remember mistake")
    if v is None:
        return False
    _mem(sess).append({"text": text, "vec": v})
    return True


async def recall(sess, text: str, http=None) -> dict | None:
    """Return {text, score} of the most similar earlier mistake (>= THRESHOLD) else None."""
    http = http or _http(sess)
    mem = _mem(sess)
    if http is None or not text or not mem:
        return None
    v = await _embed_traced(sess, http, text, "recall mistake")
    if v is None:
        return None
    best = max(((cosine(v, m["vec"]), m["text"]) for m in mem), default=(0.0, ""))
    if best[0] >= THRESHOLD:
        return {"text": best[1], "score": round(best[0], 3)}
    return None
