"""CURRENT bench replay. Routes live at / so the Ingress /app rewrite still works."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import vss
from session import ReplaySession

app = FastAPI(title="CURRENT")
client = vss.VssClient()
session = ReplaySession(client)
FRONTEND = Path(__file__).resolve().parent / "frontend"


class SelectIn(BaseModel):
    original_video: str


class TickIn(BaseModel):
    original_video: str
    time_sec: float


class ChatIn(BaseModel):
    original_video: str
    message: str


def _fail(exc: vss.VssError) -> None:
    status = exc.status if 400 <= exc.status < 600 else 502
    raise HTTPException(status_code=status, detail=str(exc)) from None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/session")
def get_session() -> dict:
    try:
        return session.public()
    except vss.VssError as exc:
        _fail(exc)


@app.post("/api/session/select")
def select_clip(body: SelectIn) -> dict:
    try:
        return session.select(body.original_video)
    except vss.VssError as exc:
        _fail(exc)


@app.post("/api/session/tick")
def tick(body: TickIn) -> dict:
    try:
        return session.tick(body.original_video, body.time_sec)
    except vss.VssError as exc:
        _fail(exc)


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")
    try:
        return session.chat(body.original_video, text)
    except vss.VssError as exc:
        _fail(exc)


@app.get("/api/videos/stream")
def stream_video(
    request: Request,
    original_video: str | None = None,
    source: str | None = None,
):
    uri = source or original_video
    if not uri:
        raise HTTPException(status_code=400, detail="original_video or source is required")
    if not uri.startswith("s3://"):
        raise HTTPException(status_code=400, detail="source must be an s3 uri")
    try:
        upstream = client.open_stream(uri, request.headers.get("range"))
    except vss.VssError as exc:
        status = exc.status if 400 <= exc.status < 600 else 502
        raise HTTPException(status_code=status, detail="video stream failed") from None
    media = upstream.headers.get("Content-Type") or ""
    if (not media) or ("octet-stream" in media):
        media = "video/mp4"
    headers = {"Accept-Ranges": upstream.headers.get("Accept-Ranges") or "bytes"}
    for name in ("Content-Length", "Content-Range"):
        value = upstream.headers.get(name)
        if value:
            headers[name] = value

    def generate():
        try:
            while True:
                chunk = upstream.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    return StreamingResponse(generate(), status_code=upstream.status, media_type=media, headers=headers)


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
