"""Per-session perception: YOLO → scene gate → Cosmos twin → curriculum coach."""
from __future__ import annotations

import asyncio
import logging
import os
import time

import aiohttp

from coach import on_twin_update, public_coach_state
from config import settings
from perception import cosmos, yolo
from session import Session
from trace import emit, span
from audio import canary as _canary

log = logging.getLogger("worker")

USE_VERIFIER = os.environ.get("USE_VERIFIER", "0").strip() in ("1", "true", "yes")


async def run_worker(sess: Session, http: aiohttp.ClientSession) -> None:
    _canary.TRACE_SESSION = sess  # lets ASR emit trace spans (main.py doesn't pass sess)
    last_frame_trace = 0.0
    while True:
        await asyncio.sleep(0.15)
        if sess.latest_frame is None:
            continue
        if sess.cosmos_inflight:
            continue

        frame = sess.latest_frame
        seq = sess.frame_seq
        force = bool(getattr(sess, "force_cosmos", False))

        now_t = time.time()
        if now_t - last_frame_trace >= 1.0:
            last_frame_trace = now_t
            await emit(sess, "frame", label="frame in", model="phone camera", sponsor="local",
                       detail=f"seq {seq} - {len(frame) // 1024} KB JPEG")

        async with span(sess, "yolo", label="YOLO11 detect", model="YOLO11", sponsor="nvidia") as sp:
            y = await yolo.infer_frame(http, frame)
            sp["detail"] = (", ".join((y.get("labels") or [])[:6]) or "no COCO objects") + (
                f" ({y.get('error')})" if y.get("error") else "")
            if not y.get("ok"):
                sp["status"] = "error"
        sess.last_yolo = y

        # Always push YOLO overlay so the UI can show boxes even when we skip Cosmos
        await sess.broadcast({
            "type": "yolo",
            "ok": y.get("ok"),
            "ms": y.get("ms"),
            "labels": y.get("labels") or [],
            "boxes": y.get("boxes") or [],
            "shape": y.get("shape"),
            "gate": y.get("gate"),
            "counts": y.get("counts") or {},
            "error": y.get("error"),
        })

        changed = yolo.changed(sess.last_yolo_sig, y["signature"])
        heartbeat = (time.time() - sess.last_cosmos_ts) >= settings.heartbeat_s
        if not force and not changed and not heartbeat:
            continue

        gate = y.get("gate") or {}
        allow = bool(force or gate.get("allow_cosmos"))
        await emit(sess, "gate", label="relevance gate", model="scene gate", sponsor="local",
                   status="ok" if allow else "skip",
                   detail=(("forced; " if force else "") + f"{gate.get('reason')}: {gate.get('detail') or ''}")
                   if allow else f"skipped: {gate.get('reason')} - {gate.get('detail') or ''}")
        if not allow:
            sess.last_yolo_sig = y["signature"]
            # Throttle skip notices
            now = time.time()
            if now - getattr(sess, "last_skip_ts", 0) > 4.0:
                sess.last_skip_ts = now
                await sess.broadcast({
                    "type": "perception_skip",
                    "reason": gate.get("reason") or "gated",
                    "detail": gate.get("detail") or "Scene not a breadboard — Cosmos not called.",
                    "yolo_ms": y.get("ms"),
                    "labels": y.get("labels") or [],
                    "gate": gate,
                    "called_cosmos": False,
                })
            continue

        sess.cosmos_inflight = True
        if force:
            sess.force_cosmos = False
        try:
            if sess.frame_seq != seq and not heartbeat and not force:
                continue

            await sess.broadcast({
                "type": "cosmos_status",
                "state": "calling",
                "yolo_ms": y.get("ms"),
                "yolo_ok": y.get("ok"),
                "labels": (y.get("labels") or [])[:8],
                "gate": gate,
                "forced": force,
                "called_cosmos": True,
            })

            async with span(sess, "cosmos", label="Cosmos3-Reason twin", model="Cosmos3-Reason",
                            sponsor="nvidia") as sp:
                twin, meta = await cosmos.extract_twin(http, frame)
                if twin:
                    sp["detail"] = (f"scene={twin.get('scene')}, {len(twin.get('components') or [])} parts, "
                                    f"{len(twin.get('nets') or [])} nets, retries={meta.get('retries')}")
                else:
                    sp["status"] = "error"
                    sp["detail"] = f"failed: {meta.get('error')}"
            if meta.get("ms"):
                p95 = cosmos.record_latency(sess.cosmos_latencies, meta["ms"])
                if p95 is not None and p95 > settings.cosmos_p95_degraded_s:
                    sess.degraded = True
                elif p95 is not None and p95 < settings.cosmos_p95_degraded_s * 0.6:
                    sess.degraded = False

            sess.last_cosmos_ts = time.time()
            sess.last_yolo_sig = y["signature"]
            timing = {
                "yolo_ms": y.get("ms"),
                "cosmos_ms": meta.get("ms"),
                "verify_ms": None,
                "llm_ms": None,
                "degraded": sess.degraded,
                "ts": time.time(),
            }

            await sess.broadcast({
                "type": "cosmos_status",
                "state": "done" if twin else "error",
                "ok": bool(twin),
                "ms": meta.get("ms"),
                "http": meta.get("http"),
                "error": meta.get("error"),
                "retries": meta.get("retries"),
                "model": meta.get("model"),
                "scene": (twin or {}).get("scene") if twin else meta.get("scene"),
                "timing": timing,
                "called_cosmos": True,
            })

            if twin is None:
                await sess.broadcast({
                    "type": "perception_error",
                    "meta": {k: meta[k] for k in meta if k != "raw"},
                    "timing": timing,
                })
                continue

            # Cosmos says this isn't a bench — talk through it, don't coach wiring
            if twin.get("scene") == "other":
                sess.twin = twin
                obs = twin.get("observation") or "I don't see a breadboard in this frame."
                await sess.broadcast({
                    "type": "twin",
                    "twin": twin,
                    "findings": [],
                    "verification": None,
                    "timing": timing,
                    "degraded": sess.degraded,
                    "mode": "cosmos+coach",
                    "coach": public_coach_state(sess),
                    "yolo": {
                        "labels": y.get("labels"),
                        "boxes": y.get("boxes"),
                        "gate": gate,
                    },
                })
                key = obs.strip().lower()
                if key not in sess.spoken_finding_ids:
                    sess.spoken_finding_ids.add(key)
                    msg = {
                        "type": "guidance",
                        "text": obs + " Point the camera at the Nano and breadboard.",
                        "finding_ids": ["scene_other"],
                        "source": "cosmos",
                        "ms": meta.get("ms"),
                        "coach": public_coach_state(sess),
                    }
                    sess.guidance_log.append(msg)
                    await sess.broadcast(msg)
                continue

            sess.twin = twin
            findings: list = []
            verification = None
            if USE_VERIFIER:
                from verifier.engine import verify_twin
                t0 = time.perf_counter()
                async with span(sess, "verify", label="verifier", model="deterministic verifier",
                                sponsor="local") as sp:
                    result = verify_twin(twin, supply_voltage=settings.supply_voltage)
                    sp["detail"] = f"{len(result['findings'])} findings, badge={result['badge']}"
                timing["verify_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                findings = result["findings"]
                verification = {"badge": result["badge"], "z3": result.get("z3")}
                sess.findings = findings
                sess.verification = result
            else:
                sess.findings = []
                sess.verification = None
                await emit(sess, "verify", label="verifier", model="deterministic verifier",
                           sponsor="local", status="skip", detail="verifier disabled (USE_VERIFIER=0)")

            sess.timings.append(timing)
            del sess.timings[:-40]

            tip = await on_twin_update(sess, http)
            if tip:
                timing["llm_ms"] = tip.get("ms")

            await sess.broadcast({
                "type": "twin",
                "twin": twin,
                "findings": findings,
                "verification": verification,
                "timing": timing,
                "degraded": sess.degraded,
                "mode": "verifier" if USE_VERIFIER else "cosmos+coach",
                "coach": public_coach_state(sess),
                "yolo": {
                    "labels": y.get("labels"),
                    "boxes": y.get("boxes"),
                    "gate": gate,
                },
            })

            if tip and tip.get("text"):
                key = tip["text"].strip().lower()
                if key not in sess.spoken_finding_ids:
                    sess.spoken_finding_ids.add(key)
                    if len(sess.spoken_finding_ids) > 40:
                        sess.spoken_finding_ids = set(list(sess.spoken_finding_ids)[-20:])
                    sess.last_guidance_ts = time.time()
                    tip["timing"] = timing
                    sess.guidance_log.append(tip)
                    await sess.broadcast(tip)
        finally:
            sess.cosmos_inflight = False
