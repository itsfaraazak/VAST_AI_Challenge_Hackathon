"""Persist session artifacts to VAST Data S3 under current-live/<session_code>/.

Fails soft: without creds or boto3 every call returns a status dict and never raises.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from config import settings
from trace import span

log = logging.getLogger("vast_store")

THUMB_INTERVAL_S = 5.0
_client = None


def _get_client():
    global _client
    if _client is None:
        import boto3  # lazy: app must boot without it
        from botocore.config import Config

        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(connect_timeout=4, read_timeout=10, retries={"max_attempts": 1},
                          s3={"addressing_style": "path"}),
        )
    return _client


def _key(sess, kind: str, ext: str) -> str:
    return f"current-live/{sess.code}/{kind}-{int(time.time() * 1000)}.{ext}"


def _put(key: str, body: bytes, ctype: str) -> None:
    _get_client().put_object(Bucket=settings.s3_bucket, Key=key, Body=body, ContentType=ctype)


async def save_event(sess, kind: str, payload) -> dict:
    """kind: 'twin' | 'frame' | 'summary' | other. payload: dict/JSON-able or JPEG bytes."""
    if not settings.s3_ready:
        return {"ok": False, "status": "disabled", "reason": "no S3 creds"}
    if isinstance(payload, (bytes, bytearray)):
        if kind == "frame":
            now = time.time()
            if now - getattr(sess, "_vast_last_frame", 0.0) < THUMB_INTERVAL_S:
                return {"ok": False, "status": "throttled"}
            sess._vast_last_frame = now
        body, ctype, ext = bytes(payload), "image/jpeg", "jpg"
    else:
        body = json.dumps(payload, default=str).encode()
        ctype, ext = "application/json", "json"
    key = _key(sess, kind, ext)
    loop = asyncio.get_running_loop()
    try:
        async with span(sess, "vast", label=f"S3 put {kind}", model="VAST S3", sponsor="vast") as s:
            await loop.run_in_executor(None, _put, key, body, ctype)
            s["detail"] = f"{key} ({len(body)} B)"
        return {"ok": True, "status": "saved", "key": key, "bytes": len(body)}
    except Exception as e:  # noqa: BLE001
        log.warning("vast save failed: %s", type(e).__name__)
        return {"ok": False, "status": "error", "reason": type(e).__name__}


async def save_summary(sess) -> dict:
    """Final session summary: steps completed, mistakes, timings."""
    cur = getattr(sess, "coach", None) or {}
    summary = {
        "session": sess.code,
        "created": sess.created,
        "ended": time.time(),
        "steps_completed": cur.get("steps_completed") or cur.get("done") or [],
        "mistakes": [f for f in (sess.findings or []) if isinstance(f, dict)],
        "timings": list(sess.timings or [])[-50:],
        "twin": sess.twin,
    }
    return await save_event(sess, "summary", summary)


async def check_s3() -> tuple[bool, str]:
    """Cheap reachability check for registry (head_bucket in a thread)."""
    if not settings.s3_ready:
        return False, "no S3 credentials in env"
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _get_client().head_bucket(Bucket=settings.s3_bucket)), 2.0)
        return True, "bucket reachable"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__
