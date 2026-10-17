#!/usr/bin/env python3
"""Live electronics coach — aiohttp server for Ingress path /app (routes at /)."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import aiohttp
from aiohttp import web

from audio import canary
from coach import (
    ask_project_opener,
    converse,
    ensure_session_coach,
    public_coach_state,
    set_step,
    resume_project,
    start_generated,
    start_project,
    teach_current_step,
)
import projects_store
from config import settings
from history import cross_corpus_demo
from sponsors import vast_store, vss_upload
from perception.worker import run_worker
from session import store
from verifier.engine import verify_twin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("app")

NO_CACHE = {"Cache-Control": "no-store, max-age=0"}  # never let a browser mix old assets with a new page
APP_DIR = Path(__file__).resolve().parent
# Prefer merged CURRENT UI from frontend/; fall back to app/static
FRONTEND = (APP_DIR.parent / "frontend").resolve()
STATIC = APP_DIR / "static"
REPLAY = APP_DIR / "replay" / "session.json"
UI_ROOT = FRONTEND if (FRONTEND / "index.html").exists() else STATIC


async def health(_: web.Request) -> web.Response:
    return web.json_response({
        "ok": True,
        "gpu": settings.gpu_ready,
        "vss": settings.vss_ready,
        "wandb": settings.wandb_ready,
        "ui": str(UI_ROOT.name),
        "services": {
            "cosmos3_reason": bool(settings.cosmos_url),
            "yolo11": bool(settings.yolo_url),
            "cosmos_embed1": bool(settings.embed_url),
            "canary_1b": bool(settings.canary_url),
            "wandb_inference": settings.wandb_ready,
            "vss_retrieval": settings.vss_ready,
        },
        "mode": "cosmos+coach",
    })


async def create_session(_: web.Request) -> web.Response:
    s = store.create()
    return web.json_response({"code": s.code})


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    code = (request.query.get("code") or "").upper()
    role = (request.query.get("role") or "phone").lower()
    if role not in ("phone", "laptop"):
        raise web.HTTPBadRequest(text="role must be phone|laptop")
    sess = store.get(code) if code else None
    if sess is None:
        sess = store.create() if not code else store.get_or_create(code)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    if role == "phone":
        sess.phone = ws
    else:
        sess.laptop = ws
    http: aiohttp.ClientSession = request.app["http"]
    if sess.worker_task is None or sess.worker_task.done():
        sess.worker_task = asyncio.create_task(run_worker(sess, http))
    ensure_session_coach(sess)
    if getattr(sess, "ticker_task", None) is None or sess.ticker_task.done():
        sess.ticker_task = asyncio.create_task(_coach_ticker(sess, http))
    await ws.send_json({
        "type": "joined",
        "code": sess.code,
        "role": role,
        "coach": public_coach_state(sess),
    })
    # Proactive ask: what do you want to build?
    if sess.coach.get("phase") == "ask_project" and not sess.coach.get("intro_sent"):
        sess.coach["intro_sent"] = True
        await ws.send_json({
            "type": "guidance",
            "text": ask_project_opener(),
            "finding_ids": ["ask_project"],
            "source": "curriculum",
            "coach": public_coach_state(sess),
        })
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                await _handle_msg(sess, role, data, http)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                sess.latest_frame = msg.data
                sess.frame_seq += 1
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                break
    finally:
        if role == "phone" and sess.phone is ws:
            sess.phone = None
        if role == "laptop" and sess.laptop is ws:
            sess.laptop = None
    return ws


async def _broadcast_guidance(sess, guidance: dict) -> None:
    if not guidance:
        return
    if guidance.get("type") != "guidance":
        guidance = {"type": "guidance", **guidance}
    sess.guidance_log.append(guidance)
    await sess.broadcast(guidance)


async def _handle_msg(sess, role: str, data: dict, http: aiohttp.ClientSession) -> None:
    typ = data.get("type")
    if typ == "frame" and role == "phone":
        import base64
        b64 = data.get("jpeg_b64") or ""
        try:
            sess.latest_frame = base64.b64decode(b64)
            sess.frame_seq += 1
        except Exception:  # noqa: BLE001
            return
    elif typ == "ask":
        question = (data.get("text") or "").strip()
        if not question:
            return
        entry = {"role": "user", "text": question}
        sess.transcript.append(entry)
        await sess.broadcast({"type": "transcript", **entry})
        await _broadcast_guidance(sess, await converse(sess, http, question))
    elif typ == "audio":
        import base64
        wav = base64.b64decode(data.get("wav_b64") or "")
        tr = await canary.transcribe(http, wav)
        text = (tr.get("text") or "").strip()
        await sess.broadcast({
            "type": "asr_status",
            "ok": tr.get("ok"),
            "ms": tr.get("ms"),
            "model": tr.get("model"),
            "error": tr.get("error"),
        })
        if text:
            entry = {"role": "user", "text": text, "ms": tr.get("ms"), "asr": "canary"}
            sess.transcript.append(entry)
            await sess.broadcast({"type": "transcript", **entry})
            await _broadcast_guidance(sess, await converse(sess, http, text))
        elif not tr.get("ok"):
            await _broadcast_guidance(sess, {
                "type": "guidance",
                "text": "I didn’t catch that on Canary — try again, or type the question.",
                "finding_ids": ["asr"],
                "source": "canary",
                "coach": public_coach_state(sess),
            })
    elif typ == "coach_start":
        prompt = (data.get("prompt") or "").strip()
        pid = (data.get("project_id") or "").strip().lower()
        note = ""
        if prompt and pid in ("", "blink") and not prompt.lower().strip(" .!").startswith("blink"):
            await sess.broadcast({"type": "guidance", "text": "Designing your circuit...", "finding_ids": ["generating"],
                                  "source": "wandb", "coach": public_coach_state(sess)})
            st, note, ok = await start_generated(sess, http, prompt, data.get("board"))
        else:
            st = start_project(sess, pid or "blink", board=data.get("board"))
        tip = await teach_current_step(sess, http, force=True)
        if note:
            text = note + " " + ((tip or {}).get("text") or "")
        else:
            pin = "GPIO2" if st.get("board") == "esp32" else "D13"
            text = f"Blink it is. {pin} → 220Ω → LED anode; cathode → GND. " + ((tip or {}).get("text") or "")
        await sess.broadcast({"type": "coach", **st})
        await _broadcast_guidance(sess, {
            "type": "guidance",
            "text": text.strip(),
            "finding_ids": (tip or {}).get("finding_ids") or [],
            "source": (tip or {}).get("source") or "curriculum",
            "ms": (tip or {}).get("ms"),
            "coach": st,
        })
    elif typ == "projects_list":
        items = await projects_store.list_projects(sess)
        await sess.broadcast({"type": "projects", "items": items or []})
    elif typ == "resume_project":
        rec = await projects_store.load(sess, str(data.get("key") or ""))
        if not rec:
            await _broadcast_guidance(sess, {"type": "guidance", "text": "I couldn't find that saved project.",
                                             "finding_ids": ["resume"], "source": "vast", "coach": public_coach_state(sess)})
            return
        st = resume_project(sess, rec)
        await sess.broadcast({"type": "coach", **st})
        await _broadcast_guidance(sess, {"type": "guidance", "text": projects_store.resume_text(rec),
                                         "finding_ids": ["resume"], "source": "vast", "coach": st})
    elif typ == "override":
        from coach import override
        g = await override(sess, http, str(data.get("action") or ""), data.get("index"))
        await sess.broadcast({"type": "coach", **public_coach_state(sess)})
        if g:
            await _broadcast_guidance(sess, g)
        try:  # keep a record of where the human disagreed with the system (learning signal)
            from sponsors import vast_store
            asyncio.create_task(vast_store.save_event(sess, "override", {"action": data.get("action"), "index": data.get("index")}))
        except Exception:  # noqa: BLE001
            pass
    elif typ == "coach_step":
        idx = data.get("index")
        if idx is None:
            return
        st = set_step(sess, int(idx))
        tip = await teach_current_step(sess, http, force=True)
        await sess.broadcast({"type": "coach", **st})
        if tip:
            await _broadcast_guidance(sess, tip)
    elif typ == "force_analyze":
        # Next worker tick may call Cosmos even if YOLO gate would skip
        sess.force_cosmos = True
        await sess.broadcast({
            "type": "cosmos_status",
            "state": "queued_force",
            "detail": "Forced analyze queued — next frame will hit Cosmos.",
        })
    elif typ == "ping":
        await sess.broadcast({"type": "pong", "t": data.get("t")})


async def sse_handler(request: web.Request) -> web.StreamResponse:
    code = (request.query.get("code") or "").upper()
    sess = store.get(code)
    if not sess:
        raise web.HTTPNotFound(text="unknown session")
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    sess.sse_queues.append(q)
    resp = web.StreamResponse(status=200, reason="OK", headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    })
    await resp.prepare(request)
    try:
        await resp.write(b"event: joined\ndata: " + json.dumps({"code": sess.code}).encode() + b"\n\n")
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15)
                await resp.write(b"data: " + json.dumps(msg).encode() + b"\n\n")
            except asyncio.TimeoutError:
                await resp.write(b": keepalive\n\n")
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        if q in sess.sse_queues:
            sess.sse_queues.remove(q)
    return resp


async def api_verify(request: web.Request) -> web.Response:
    body = await request.json()
    result = verify_twin(
        body.get("twin") or body,
        supply_voltage=float(body.get("supply_voltage") or settings.supply_voltage),
    )
    return web.json_response({
        "findings": result["findings"],
        "badge": result["badge"],
        "simulation": result.get("simulation"),
        "z3": result.get("z3"),
    })


async def api_cross_corpus(request: web.Request) -> web.Response:
    http: aiohttp.ClientSession = request.app["http"]
    data = await cross_corpus_demo(http)
    return web.json_response(data)


async def api_sponsors(request: web.Request) -> web.Response:
    try:
        from sponsors.registry import sponsor_status
        return web.json_response(await sponsor_status(request.app["http"]))
    except Exception as e:  # noqa: BLE001
        log.warning("sponsors unavailable: %s", e)
        return web.json_response([], status=404)


async def _coach_ticker(sess, http) -> None:
    """Always-on: let the coach speak up on its own (idle hints, proactive corrections)."""
    try:
        from coach import tick
    except ImportError:
        return
    while sess.phone is not None or sess.laptop is not None:
        await asyncio.sleep(4)
        try:
            tip = await tick(sess, http)
            if tip:
                await _broadcast_guidance(sess, tip)
        except Exception:  # noqa: BLE001
            log.exception("coach tick failed")


async def api_replay(_: web.Request) -> web.Response:
    if not REPLAY.exists():
        return web.json_response({"events": []})
    return web.json_response(json.loads(REPLAY.read_text()))


async def api_upload(request: web.Request) -> web.Response:
    code = request.match_info["code"].upper()
    sess = store.get(code)
    if sess is None:
        raise web.HTTPNotFound(text="unknown session")
    http: aiohttp.ClientSession = request.app["http"]
    data, filename = b"", "session.webm"
    if request.content_type.startswith("multipart/"):
        reader = await request.multipart()
        async for part in reader:
            if part.name == "file":
                filename = part.filename or filename
                data = bytes(await part.read(decode=False))
    else:
        data = await request.read()
        if "mp4" in request.content_type:
            filename = "session.mp4"
    if not data:
        return web.json_response({"ok": False, "status": "empty", "detail": "no video data", "object_key": None}, status=400)
    filename = f"current-{sess.code}-{filename.rsplit('/', 1)[-1]}"
    res = await vss_upload.upload_session_video(http, data, filename, sess)
    try:  # best-effort copy to VAST S3
        if settings.s3_ready:
            from sponsors.vast_store import _key, _put
            key = _key(sess, "video", "mp4" if filename.endswith(".mp4") else "webm")
            await asyncio.get_running_loop().run_in_executor(None, _put, key, data, "video/webm")
            res["s3_key"] = key
    except Exception as e:  # noqa: BLE001
        res["s3_error"] = type(e).__name__
    res.pop("response", None)
    await sess.broadcast({"type": "vss_upload", "ok": res["ok"], "object_key": res.get("object_key"), "detail": res.get("detail", "")})
    return web.json_response(res)


async def api_upload_limits(request: web.Request) -> web.Response:
    return web.json_response({"max_mb": await vss_upload.max_upload_mb(request.app["http"]) if settings.vss_ready else 0})


async def api_projects(request: web.Request) -> web.Response:
    items = await projects_store.list_projects()
    return web.json_response(items or [])


async def index(_: web.Request) -> web.Response:
    return web.FileResponse(UI_ROOT / "index.html", headers=NO_CACHE)


async def on_start(app: web.Application) -> None:
    app["http"] = aiohttp.ClientSession()
    log.info(
        "listening port=%s gpu=%s vss=%s wandb=%s ui=%s",
        settings.port, settings.gpu_ready, settings.vss_ready, settings.wandb_ready, UI_ROOT,
    )
    if settings.s3_ready:
        app["seed_task"] = asyncio.create_task(_seed(app))


async def _seed(app: web.Application) -> None:
    try:
        log.info("project seed: %s", await projects_store.seed_demo(app["http"]))
    except Exception as e:  # noqa: BLE001
        log.warning("project seed failed: %s", type(e).__name__)


async def on_stop(app: web.Application) -> None:
    await app["http"].close()


def create_app() -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_get("/health", health)
    app.router.add_post("/api/session", create_session)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/sse", sse_handler)
    app.router.add_post("/api/verify", api_verify)
    app.router.add_get("/api/cross-corpus", api_cross_corpus)
    app.router.add_get("/api/replay", api_replay)
    app.router.add_get("/api/sponsors", api_sponsors)
    app.router.add_post("/api/session/{code}/upload", api_upload)
    app.router.add_get("/api/vss-limits", api_upload_limits)
    app.router.add_get("/api/projects", api_projects)
    app.router.add_get("/", index)
    # CURRENT frontend assets at /app.js /styles.css (relative to index)
    if UI_ROOT.exists():
        async def _asset(request: web.Request) -> web.FileResponse:
            name = request.match_info["name"]
            path = (UI_ROOT / name).resolve()
            if not str(path).startswith(str(UI_ROOT.resolve())) or not path.is_file():
                raise web.HTTPNotFound()
            return web.FileResponse(path, headers=NO_CACHE)

        app.router.add_get("/{name:[A-Za-z0-9_.\\-]+\\.(?:js|css|json|webmanifest|svg|png|glb|md)}", _asset)
    if STATIC.exists():
        app.router.add_static("/static/", STATIC, show_index=False)
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=settings.port)
