"""Additive HTTP/WS routes for sketch generation + external-agent state. Wire: register(app) in create_app."""
from __future__ import annotations

from aiohttp import web

import codegen
import projects_store
from coach import ensure_session_coach, public_coach_state, resume_project
from session import store


def _sess(request: web.Request, code: str | None = None):
    code = (code or request.query.get("code") or "").strip()
    sess = store.get(code) if code else None
    if not sess:
        raise web.HTTPNotFound(text='{"error":"unknown session"}', content_type="application/json")
    ensure_session_coach(sess)
    return sess


async def sketch_message(sess, data: dict, http) -> None:
    """ws {type:'sketch_request', instruction, undo?} -> broadcast {type:'sketch'}."""
    if data.get("undo"):
        res = codegen.undo(sess) or codegen.current(sess)
        res = {**res, "notes": (res.get("notes") or []) + ["Undid last change."]}
    else:
        res = await codegen.generate_sketch(sess, http, (data.get("instruction") or "").strip() or None, compile=True)
    await sess.broadcast({"type": "sketch", "code": res["code"], "board": res["board"], "notes": res.get("notes", []),
                          "pins": res.get("pins", []), "can_undo": bool(sess.coach.get("sketch_history"))})


async def get_sketch(request: web.Request) -> web.Response:
    sess = _sess(request)
    cur = codegen.current(sess)
    return web.json_response({**cur, "can_undo": bool(sess.coach.get("sketch_history"))})


async def post_sketch(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    sess = _sess(request, str(body.get("code") or ""))
    if body.get("undo"):
        res = codegen.undo(sess) or codegen.current(sess)
    else:
        res = await codegen.generate_sketch(sess, request.app["http"], (body.get("instruction") or "").strip() or None, compile=True)
    await sess.broadcast({"type": "sketch", "code": res["code"], "board": res["board"], "notes": res.get("notes", []),
                          "pins": res.get("pins", []), "can_undo": bool(sess.coach.get("sketch_history"))})
    return web.json_response(res)


async def download(request: web.Request) -> web.Response:
    sess = _sess(request)
    cur = codegen.current(sess)
    board = request.query.get("board") or cur["board"]
    code = cur["code"]
    if codegen._board(board) != cur["board"]:  # other board requested: regenerate deterministic template
        ctx = codegen.context(sess)
        ctx["board"] = codegen._board(board)
        code = codegen.fallback_sketch(ctx)
    return web.Response(text=code, content_type="text/plain",
                        headers={"Content-Disposition": 'attachment; filename="current_sketch.ino"'})


def compact_state(sess) -> dict:
    st = public_coach_state(sess)
    p = st.get("project") or {}
    step = st.get("step") or {}
    twin = getattr(sess, "twin", None)
    return {
        "code": sess.code,
        "project": {"id": p.get("id"), "title": p.get("title"), "pitch": p.get("pitch"), "mcu": p.get("mcu"),
                    "parts_list": p.get("parts_list"),
                    "steps": [{"title": s.get("title"), "pins": s.get("pins"), "wires": s.get("wires")} for s in p.get("steps") or []]} if p else None,
        "step_index": st.get("step_index"), "step": {"title": step.get("title"), "action": step.get("action")} if step else None,
        "board": st.get("board"), "parts_seen": projects_store.parts_seen(sess), "twin": twin,
        "findings": [{k: f.get(k) for k in ("id", "severity", "text", "message") if k in f}
                     for f in (getattr(sess, "findings", None) or [])][:20],
        "mistakes": st.get("mistakes"), "sketch": codegen.current(sess),
    }


async def get_state(request: web.Request) -> web.Response:
    return web.json_response(compact_state(_sess(request)), dumps=lambda o: __import__("json").dumps(o, default=str))


async def resume(request: web.Request) -> web.Response:
    sess = _sess(request, request.match_info["code"])
    body = await request.json() if request.can_read_body else {}
    rec = await projects_store.load(sess, str(body.get("key") or request.query.get("key") or ""))
    if not rec:
        return web.json_response({"error": "saved project not found"}, status=404)
    resume_project(sess, rec)
    if rec.get("sketch"):
        b = codegen._board(rec.get("board"))
        sess.coach["sketch_current"] = {"code": rec["sketch"], "board": b, "pins": [], "notes": ["Restored from VAST S3."]}
    await sess.broadcast({"type": "coach", **public_coach_state(sess)})
    return web.json_response({"ok": True, "title": rec.get("title"), "step_index": rec.get("step_index")})


async def projects(request: web.Request) -> web.Response:
    return web.json_response(await projects_store.list_projects() or [])


def register(app: web.Application) -> None:
    app.router.add_get("/api/sketch", get_sketch)
    app.router.add_post("/api/sketch", post_sketch)
    app.router.add_get("/api/sketch/download", download)
    app.router.add_get("/api/state", get_state)
    app.router.add_post("/api/session/{code}/resume", resume)
