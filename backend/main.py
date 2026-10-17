"""CURRENT live bench. Camera frames in → Cosmos out. VAST used as few-shot examples."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import cosmos
import vss
from session import LiveSession

app = FastAPI(title="CURRENT")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = vss.VssClient()
vision = cosmos.CosmosClient()
session = LiveSession(client, vision)

# Prefer repo-root frontend (camera UI). Fall back to backend/frontend.
_ROOT = Path(__file__).resolve().parent
FRONTEND = _ROOT.parent / "frontend"
if not (FRONTEND / "index.html").exists():
    FRONTEND = _ROOT / "frontend"


class FrameIn(BaseModel):
    image_jpeg_b64: str = Field(min_length=32)


class ChatIn(BaseModel):
    message: str


def _fail(exc: Exception) -> None:
    if isinstance(exc, vss.VssError):
        status = exc.status if 400 <= exc.status < 600 else 502
        raise HTTPException(status_code=status, detail=str(exc)) from None
    if isinstance(exc, cosmos.CosmosError):
        status = exc.status if 400 <= exc.status < 600 else 502
        raise HTTPException(status_code=status, detail=str(exc)) from None
    raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": "live"}


@app.get("/api/session")
def get_session() -> dict:
    try:
        return session.public()
    except Exception as exc:  # noqa: BLE001 — surface to UI fast
        _fail(exc)


@app.post("/api/frame")
def post_frame(body: FrameIn) -> dict:
    raw = body.image_jpeg_b64
    if "," in raw[:64]:
        raw = raw.split(",", 1)[1]
    try:
        return session.analyze_frame(raw)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")
    try:
        return session.chat(text)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
