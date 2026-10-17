"""Canary ASR via POST /v1/audio/transcriptions."""
from __future__ import annotations

import logging

import aiohttp

from config import settings
from timing import timed

log = logging.getLogger("canary")

_MODEL: str | None = None


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


async def transcribe(http: aiohttp.ClientSession, wav: bytes) -> dict:
    if not settings.gpu_token:
        return {"text": "", "ok": False, "error": "no_token"}
    model = await resolve_model(http)
    form = aiohttp.FormData()
    form.add_field("model", model)
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
                # retry without model / alternate name
                for alt in ("", "nvidia/canary-1b-flash", "canary-1b"):
                    if alt == model:
                        continue
                    form2 = aiohttp.FormData()
                    if alt:
                        form2.add_field("model", alt)
                    form2.add_field("file", wav, filename="audio.wav", content_type="audio/wav")
                    async with http.post(
                        settings.canary_url + "/v1/audio/transcriptions",
                        data=form2,
                        headers=headers,
                        timeout=60,
                    ) as resp2:
                        if resp2.status < 400:
                            data = await resp2.json(content_type=None)
                            text = data.get("text") if isinstance(data, dict) else str(data)
                            return {"text": text or "", "ok": True, "ms": t["ms"], "model": alt or "default"}
                return {"text": "", "ok": False, "http": resp.status, "ms": t["ms"]}
            data = await resp.json(content_type=None)
    text = data.get("text") if isinstance(data, dict) else str(data)
    return {"text": text or "", "ok": True, "ms": t["ms"], "model": model}
