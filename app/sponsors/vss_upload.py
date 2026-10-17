"""Upload the recorded session video to VAST VSS (Video Search & Summary). Fails soft."""
from __future__ import annotations

import logging

import aiohttp

from config import settings
from history import login
import history
from trace import span

log = logging.getLogger("vss_upload")

CUSTOM_PROMPT = (
    "Electronics breadboard build session. Describe which components (LED, resistor, jumper wires, "
    "microcontroller board) appear, the wiring steps in order, and any mistakes such as reversed LED "
    "polarity, missing resistor, shorts or wrong pins, and whether they were corrected."
)[:800]
DEFAULT_MAX_MB = 25.0


async def max_upload_mb(http: aiohttp.ClientSession) -> float:
    try:
        token = await login(http)
        if not token:
            return DEFAULT_MAX_MB
        async with http.get(settings.vss_url + "/api/v1/config",
                            headers={"Authorization": f"Bearer {token}"}, timeout=15) as r:
            d = await r.json(content_type=None)
        return float((d.get("app") or {}).get("max_upload_size_mb") or DEFAULT_MAX_MB)
    except Exception:  # noqa: BLE001
        return DEFAULT_MAX_MB


async def upload_session_video(http: aiohttp.ClientSession, data: bytes, filename: str, sess) -> dict:
    res = {"ok": False, "status": "error", "detail": "", "object_key": None}
    if not settings.vss_ready:
        res.update(status="disabled", detail="VSS not configured")
        return res
    board = (getattr(sess, "coach", None) or {}).get("board") or "nano"
    try:
        async with span(sess, "vss", label="upload session video", model="VAST VSS", sponsor="vast") as s:
            limit = await max_upload_mb(http)
            if len(data) > limit * 1024 * 1024:
                res.update(status="too_large", detail=f"{len(data)/1e6:.1f} MB > {limit:g} MB limit")
                s["status"] = "error"; s["detail"] = res["detail"]
                return res
            token = await login(http)
            if not token:
                res.update(status="auth", detail="VSS login failed")
                s["status"] = "error"; s["detail"] = res["detail"]
                return res
            ctype = "video/mp4" if filename.lower().endswith(".mp4") else "video/webm"
            form = aiohttp.FormData()
            form.add_field("file", data, filename=filename, content_type=ctype)
            form.add_field("is_public", "true")
            form.add_field("tags", f"current,electronics,blink,{board},session-{sess.code}")
            form.add_field("custom_prompt", CUSTOM_PROMPT)
            form.add_field("camera_id", "current-bench")
            form.add_field("capture_type", "video")
            form.add_field("location", "hackathon-bench")
            async with http.post(settings.vss_url + "/api/v1/videos/upload", data=form,
                                 headers={"Authorization": f"Bearer {token}"},
                                 timeout=aiohttp.ClientTimeout(total=120)) as r:
                if r.status == 401:
                    history._JWT = None
                body = await r.json(content_type=None) if r.content_type == "application/json" else {"raw": (await r.text())[:200]}
            if r.status >= 400:
                res.update(status=f"http_{r.status}", detail=str(body)[:300])
                s["status"] = "error"; s["detail"] = res["detail"]
                return res
            key = None
            if isinstance(body, dict):
                key = body.get("object_key") or body.get("key") or body.get("s3_key") or body.get("filename") or body.get("video_id")
            res.update(ok=True, status="uploaded", object_key=key, detail=f"{len(data)} B", response=body if isinstance(body, dict) else None)
            s["detail"] = f"{key} ({len(data)} B)"
    except Exception as e:  # noqa: BLE001
        log.warning("vss upload failed: %s", type(e).__name__)
        res.update(status="error", detail=f"{type(e).__name__}: {e}"[:300])
    return res
