"""Session memory via VSS search / agent-qa (team uploads + cross-corpus demo)."""
from __future__ import annotations

import json
import logging

import aiohttp

from config import settings

log = logging.getLogger("history")

_JWT: str | None = None


async def login(http: aiohttp.ClientSession) -> str | None:
    global _JWT
    if not settings.vss_ready:
        return None
    if _JWT:
        return _JWT
    async with http.post(
        settings.vss_url + "/api/v1/auth/login",
        json={"username": settings.vss_user, "password": settings.vss_password},
        timeout=30,
    ) as resp:
        if resp.status >= 400:
            return None
        data = await resp.json()
        _JWT = data["access_token"]
        return _JWT


async def search_my_mistakes(http: aiohttp.ClientSession, question: str) -> dict:
    token = await login(http)
    if not token:
        return {"text": "History search unavailable.", "evidence": None}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "query": "electronics wiring mistake polarity missing resistor short corrected",
        "top_k": 5,
        "include_public": False,
        "min_similarity": 0.25,
    }
    try:
        async with http.post(settings.vss_url + "/api/v1/search", json=body, headers=headers, timeout=60) as resp:
            if resp.status >= 400:
                async with http.post(
                    settings.vss_url + "/api/v1/agent/ask",
                    json={"question": question},
                    headers=headers,
                    timeout=90,
                ) as resp2:
                    data = await resp2.json()
                    return {"text": (data.get("answer") or "No prior mistakes found.")[:240], "evidence": data}
            data = await resp.json()
    except Exception:  # noqa: BLE001
        return {"text": "History search failed.", "evidence": None}
    hits = data.get("results") or data.get("hits") or data.get("segments") or []
    if not hits:
        return {"text": "I have not indexed a prior mistake for you yet.", "evidence": None}
    h0 = hits[0] if isinstance(hits[0], dict) else {}
    ts = h0.get("start_time") or h0.get("best_match_start_sec") or h0.get("timestamp")
    src = h0.get("source") or h0.get("preview_source") or h0.get("original_video")
    text = f"Yes — similar issue at t={ts}s in {src}."
    return {"text": text[:240], "evidence": {"source": src, "timestamp": ts}}


async def cross_corpus_demo(http: aiohttp.ClientSession) -> dict:
    token = await login(http)
    if not token:
        return {"ok": False, "error": "no_vss"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "query": "person close to a moving vehicle",
        "top_k": 3,
        "include_public": True,
        "min_similarity": 0.3,
    }
    try:
        async with http.post(settings.vss_url + "/api/v1/search", json=body, headers=headers, timeout=60) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                return {"ok": False, "http": resp.status, "error": str(data)[:300]}
            # compact evidence for UI
            chunks = data.get("chunk_results") or data.get("results") or []
            brief = []
            for c in (chunks[:3] if isinstance(chunks, list) else []):
                if not isinstance(c, dict):
                    continue
                brief.append({
                    "source": c.get("preview_source") or c.get("source") or c.get("original_video"),
                    "start": c.get("best_match_start_sec") or c.get("start_time"),
                    "score": c.get("similarity_score"),
                    "snippet": (c.get("reasoning_content") or "")[:180],
                })
            return {"ok": True, "hits": brief, "count": len(brief)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": type(e).__name__}
