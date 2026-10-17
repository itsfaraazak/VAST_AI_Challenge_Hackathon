"""Canary ASR via POST /v1/audio/transcriptions."""
from __future__ import annotations

import json
import logging

import aiohttp

from config import settings
from timing import timed
from trace import emit

log = logging.getLogger("canary")

_MODEL: str | None = None
TRACE_SESSION = None  # set by perception.worker; used for trace events


async def resolve_model(http: aiohttp.ClientSession) -> str:
    global _MODEL
    if settings.canary_model:
        _MODEL = settings.canary_model
        return _MODEL
    if _MODEL:
        return _MODEL
    headers = {"Authorization": f"Bearer {settings.gpu_token}"}
    # Try openapi / models
    for path in ("/v1/models", "/openapi.json"):
        try:
            async with http.get(settings.canary_url + path, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()
                if "data" in data and data["data"]:
                    _MODEL = data["data"][0]["id"]
                    return _MODEL
        except Exception:  # noqa: BLE001
            continue
    # Common Canary NIM id
    _MODEL = "canary-1b"
    return _MODEL


async def transcribe(http: aiohttp.ClientSession, wav: bytes, sess=None) -> dict:
    sess = sess or TRACE_SESSION
    if sess is None:
        return await _transcribe(http, wav)
    sid = await emit(sess, "asr", label="Canary ASR", model="Canary-1B", sponsor="nvidia", status="start")
    try:
        r = await _transcribe(http, wav)
    except Exception as e:  # noqa: BLE001
        await emit(sess, "asr", label="Canary ASR", model="Canary-1B", sponsor="nvidia", status="error",
                   detail=f"{type(e).__name__}: {e}", sid=sid)
        raise
    await emit(sess, "asr", label="Canary ASR", model="Canary-1B", sponsor="nvidia",
               status="ok" if r.get("ok") else "error", ms=r.get("ms"),
               detail=(r.get("text") or r.get("error") or f"http {r.get('http')}")[:120], sid=sid)
    return r


async def _transcribe(http: aiohttp.ClientSession, wav: bytes) -> dict:
    """Riva-style NIM: `language` (en-US) is required, `model` names are rejected."""
    if not settings.gpu_token:
        return {"text": "", "ok": False, "error": "no_token"}
    form = aiohttp.FormData()
    form.add_field("language", settings.canary_language)
    form.add_field("file", wav, filename="audio.wav", content_type="audio/wav")
    headers = {"Authorization": f"Bearer {settings.gpu_token}"}
    with timed("canary") as t:
        async with http.post(
            settings.canary_url + "/v1/audio/transcriptions",
            data=form,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            raw = await resp.read()
            if resp.status >= 400:
                return {"text": "", "ok": False, "http": resp.status, "error": raw[:160].decode("utf-8", "replace"), "ms": t["ms"]}
            data = json.loads(raw)
    text = data.get("text") if isinstance(data, dict) else str(data)
    return {"text": text or "", "ok": True, "ms": t["ms"], "model": "canary-1b"}
