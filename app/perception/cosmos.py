"""Cosmos3-Reason twin extraction via image_url (real NIM call)."""
from __future__ import annotations

import base64
import json
import logging

import aiohttp

from config import settings
from perception.twin_parse import TwinParseError, parse_twin
from timing import timed

log = logging.getLogger("cosmos")

TWIN_PROMPT = """You are a vision model looking at a camera frame of an electronics workbench.

FIRST classify the scene:
- scene="bench" only if you clearly see a solderless breadboard and/or Arduino / MCU / discrete parts being wired.
- scene="other" if you see a person, face, clothing, empty desk, or anything that is NOT a breadboard build.

If scene="other", return ONLY:
{"scene":"other","observation":"<one sentence of what you actually see>","components":[],"nets":[],"placements":[],"wiring_check":{"ok":false,"issues":["not a breadboard scene"]}}

If scene="bench", return ONLY JSON:
{
  "scene":"bench",
  "observation":"<2 sentences: what is already placed, what looks wrong>",
  "components":[{"id":"nano1","type":"arduino","value":"nano"},{"id":"r1","type":"resistor","value":"220"},{"id":"d1","type":"led","value":"red"}],
  "nets":[["nano1.d13","r1.a"],["r1.b","d1.a"],["d1.k","nano1.gnd"]],
  "placements":[
    {"id":"d1","part":"led","anode_hole":"E12","cathode_hole":"E13","ok":true,"note":"long leg toward resistor"},
    {"id":"r1","part":"resistor","holes":["A12","D13"],"ok":true,"note":"series from D13 row to LED anode row"}
  ],
  "wiring_check":{
    "target":"blink_nano_external_led",
    "expected":"D13 -> 220ohm -> LED anode; LED cathode -> GND",
    "ok":false,
    "issues":["cathode not yet on GND"]
  },
  "supply_voltage":5
}

Rules:
- Breadboard holes: letter column A–J + row number (e.g. E15). Be honest if unsure — set ok=false and say so in note.
- Types allowed: resistor, led, battery, supply, switch, wire, capacitor, diode, arduino, breadboard, unknown.
- LED anode pin suffix .a ; cathode .k
- JSON only. No markdown.
"""


async def _model_id(session: aiohttp.ClientSession) -> str:
    headers = {"Authorization": f"Bearer {settings.gpu_token}"}
    async with session.get(settings.cosmos_url + "/v1/models", headers=headers, timeout=20) as resp:
        data = await resp.json()
        return data["data"][0]["id"]


async def extract_twin(session: aiohttp.ClientSession, jpeg: bytes) -> tuple[dict | None, dict]:
    """POST /v1/chat/completions with image_url data-JPEG. Returns (twin, meta)."""
    if not settings.gpu_ready:
        return None, {"ok": False, "error": "gpu_not_configured", "ms": 0}
    headers = {"Authorization": f"Bearer {settings.gpu_token}", "Content-Type": "application/json"}
    model = await _model_id(session)
    b64 = base64.b64encode(jpeg).decode()
    content = [
        {"type": "text", "text": TWIN_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 768,
        "messages": [{"role": "user", "content": content}],
    }
    text = None
    meta: dict = {"ok": False, "ms": 0, "retries": 0, "model": model, "endpoint": "chat/completions"}
    for attempt in range(2):
        with timed("cosmos") as t:
            async with session.post(
                settings.cosmos_url + "/v1/chat/completions",
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                raw = await resp.read()
                meta["http"] = resp.status
                if resp.status >= 400:
                    meta["error"] = f"http_{resp.status}"
                    meta["ms"] = t["ms"]
                    return None, meta
                data = json.loads(raw)
        meta["ms"] = (meta.get("ms") or 0) + (t["ms"] or 0)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            meta["error"] = "bad_response_shape"
            return None, meta
        try:
            twin = parse_twin(text)
            meta["ok"] = True
            meta["retries"] = attempt
            meta["scene"] = twin.get("scene")
            return twin, meta
        except (TwinParseError, json.JSONDecodeError, ValueError, TypeError):
            meta["retries"] = attempt + 1
            body = {
                "model": model,
                "temperature": 0,
                "max_tokens": 768,
                "messages": [
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": text or ""},
                    {"role": "user", "content": "Invalid JSON. Return ONLY the twin JSON object, no markdown."},
                ],
            }
    meta["error"] = "invalid_json"
    meta["ok"] = False
    return None, meta


def record_latency(latencies: list[float], ms: float | None, window: int = 20) -> float | None:
    if ms is None:
        return None
    latencies.append(ms / 1000.0)
    del latencies[:-window]
    if not latencies:
        return None
    xs = sorted(latencies)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]
