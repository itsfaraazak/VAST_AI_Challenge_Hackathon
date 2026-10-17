"""CURRENT MCP server (stdio). Lets Claude Code / Cursor read the live digital twin and edit the sketch.

Uses the official `mcp` SDK when importable, else a minimal JSON-RPC 2.0 stdio implementation.
Env: CURRENT_URL (default http://localhost:18080).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("CURRENT_URL", "http://localhost:18080").rstrip("/")


def _http(method: str, path: str, body: dict | None = None, timeout: float = 90):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode(errors="replace")[:300]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"CURRENT server unreachable at {BASE}: {type(e).__name__}"}


def _q(code: str) -> str:
    return urllib.parse.quote(code)


def current_get_state(code: str) -> dict:
    """Compact live state: project, step, board, parts seen, twin, findings, mistakes, sketch."""
    return _http("GET", f"/api/state?code={_q(code)}")


def current_get_sketch(code: str) -> dict:
    """Current .ino sketch (code, board, pins, notes) for the bench."""
    return _http("GET", f"/api/sketch?code={_q(code)}")


def current_update_sketch(code: str, instruction: str) -> dict:
    """Regenerate the sketch from a natural-language instruction, grounded in the live twin."""
    return _http("POST", "/api/sketch", {"code": code, "instruction": instruction})


def current_list_projects() -> dict:
    """List saved projects (VAST S3) with their keys."""
    return _http("GET", "/api/projects")


def current_resume_project(code: str, key: str) -> dict:
    """Load a saved project into a live session."""
    return _http("POST", f"/api/session/{_q(code)}/resume", {"key": key})


def current_get_twin(code: str) -> dict:
    """Only the observed digital twin (components, connections) for the session."""
    st = _http("GET", f"/api/state?code={_q(code)}")
    if isinstance(st, dict) and "error" not in st:
        return {"twin": st.get("twin"), "parts_seen": st.get("parts_seen"), "board": st.get("board")}
    return st


TOOLS = [current_get_state, current_get_sketch, current_update_sketch, current_list_projects,
         current_resume_project, current_get_twin]
_SCHEMAS = {
    "current_get_state": ["code"], "current_get_sketch": ["code"], "current_update_sketch": ["code", "instruction"],
    "current_list_projects": [], "current_resume_project": ["code", "key"], "current_get_twin": ["code"],
}


def _tool_list() -> list[dict]:
    return [{"name": f.__name__, "description": f.__doc__ or "",
             "inputSchema": {"type": "object", "properties": {a: {"type": "string"} for a in _SCHEMAS[f.__name__]},
                             "required": _SCHEMAS[f.__name__]}} for f in TOOLS]


def handle(msg: dict) -> dict | None:
    """Minimal MCP JSON-RPC handler (fallback transport)."""
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        return None  # notification
    ok = lambda r: {"jsonrpc": "2.0", "id": mid, "result": r}  # noqa: E731
    if method == "initialize":
        return ok({"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
                   "capabilities": {"tools": {}}, "serverInfo": {"name": "current", "version": "0.1.0"}})
    if method == "tools/list":
        return ok({"tools": _tool_list()})
    if method == "tools/call":
        p = msg.get("params") or {}
        fn = next((f for f in TOOLS if f.__name__ == p.get("name")), None)
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        try:
            res = fn(**(p.get("arguments") or {}))
        except TypeError as e:
            res = {"error": str(e)}
        return ok({"content": [{"type": "text", "text": json.dumps(res, default=str)}], "isError": "error" in res if isinstance(res, dict) else False})
    if method == "ping":
        return ok({})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}


def run_minimal() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:  # noqa: BLE001
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


def main() -> None:
    if os.environ.get("CURRENT_MCP_MINIMAL") != "1":
        try:
            from mcp.server.fastmcp import FastMCP
        except Exception:  # noqa: BLE001
            FastMCP = None
        if FastMCP:
            srv = FastMCP("current")
            for f in TOOLS:
                srv.tool()(f)
            srv.run()
            return
    run_minimal()


if __name__ == "__main__":
    main()
