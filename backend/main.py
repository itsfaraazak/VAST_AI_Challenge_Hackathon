"""CURRENT live bench + Wokwi sim connector.

Camera frames → Cosmos. Circuit note → simulator advice / embed.
VAST captions used as few-shot examples for chat.
"""

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
from simulator import SimState

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
sim = SimState()

# Prefer repo-root frontend (camera UI). Fall back to backend/frontend.
_ROOT = Path(__file__).resolve().parent
FRONTEND = _ROOT.parent / "frontend"
if not (FRONTEND / "index.html").exists():
    FRONTEND = _ROOT / "frontend"


class FrameIn(BaseModel):
    image_jpeg_b64: str = Field(min_length=32)


class ChatIn(BaseModel):
    message: str


class SimAdviseIn(BaseModel):
    goal: str | None = None
    question: str | None = None
    circuit: dict | None = None


class SimApplyIn(BaseModel):
    action_id: str
    circuit: dict | None = None


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
    return {"status": "ok", "mode": "live", "sim": True}


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
        result = session.analyze_frame(raw)
        # Keep sim in sync with the live circuit note.
        circuit = result.get("circuit") or session.circuit_snapshot()
        sim.sync(circuit)
        if result.get("alerts"):
            advice = sim.advise(question="warning")
            if advice.get("next_actions"):
                result["sim_hint"] = advice.get("advice")
                result["sim"] = {
                    "ok": advice.get("ok"),
                    "issues": advice.get("issues"),
                    "next_actions": advice.get("next_actions"),
                    "advice": advice.get("advice"),
                }
        return result
    except Exception as exc:  # noqa: BLE001
        _fail(exc)


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")
    try:
        return session.chat(text, sim_state=sim)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)


@app.get("/api/sim")
def get_sim() -> dict:
    # Refresh from live circuit before returning.
    sim.sync(session.circuit_snapshot())
    return sim.snapshot()


@app.post("/api/sim/sync")
def sync_sim() -> dict:
    return sim.sync(session.circuit_snapshot())


@app.post("/api/sim/advise")
def advise_sim(body: SimAdviseIn) -> dict:
    circuit = body.circuit if body.circuit is not None else session.circuit_snapshot()
    sim.sync(circuit)
    return sim.advise(question=body.question or "", goal=body.goal or "arduino_nano_blink")


@app.post("/api/sim/apply")
def apply_sim(body: SimApplyIn) -> dict:
    action = (body.action_id or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="action_id is required")
    if body.circuit is not None:
        sim.sync(body.circuit)
    else:
        sim.sync(session.circuit_snapshot())
    return sim.apply(action)


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
