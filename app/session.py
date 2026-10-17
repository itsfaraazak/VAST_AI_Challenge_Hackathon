"""In-memory WebSocket rooms keyed by 6-character session codes."""
from __future__ import annotations

import asyncio
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

ALPHABET = string.ascii_uppercase + string.digits


def new_code(n: int = 6) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


@dataclass
class Session:
    code: str
    created: float = field(default_factory=time.time)
    phone: web.WebSocketResponse | None = None
    laptop: web.WebSocketResponse | None = None
    sse_queues: list[asyncio.Queue] = field(default_factory=list)
    twin: dict | None = None
    findings: list[dict] = field(default_factory=list)
    verification: dict | None = None
    transcript: list[dict] = field(default_factory=list)
    guidance_log: list[dict] = field(default_factory=list)
    spoken_finding_ids: set[str] = field(default_factory=set)
    last_guidance_ts: float = 0.0
    last_yolo_sig: str | None = None
    last_cosmos_ts: float = 0.0
    cosmos_inflight: bool = False
    latest_frame: bytes | None = None
    frame_seq: int = 0
    cosmos_latencies: list[float] = field(default_factory=list)
    degraded: bool = False
    timings: list[dict] = field(default_factory=list)
    coach: dict | None = None
    force_cosmos: bool = False
    last_yolo: dict | None = None
    last_skip_ts: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    worker_task: asyncio.Task | None = None
    ticker_task: asyncio.Task | None = None

    async def broadcast(self, msg: dict) -> None:
        dead: list[web.WebSocketResponse] = []
        for ws in (self.phone, self.laptop):
            if ws is not None and not ws.closed:
                try:
                    await ws.send_json(msg)
                except Exception:  # noqa: BLE001
                    dead.append(ws)
        if self.phone in dead:
            self.phone = None
        if self.laptop in dead:
            self.laptop = None
        for q in list(self.sse_queues):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        for _ in range(20):
            code = new_code()
            if code not in self._sessions:
                s = Session(code=code)
                self._sessions[code] = s
                return s
        raise RuntimeError("could not allocate session code")

    def get(self, code: str) -> Session | None:
        return self._sessions.get(code.upper())

    def get_or_create(self, code: str | None) -> Session:
        if code:
            s = self.get(code)
            if s:
                return s
        return self.create()


store = SessionStore()
