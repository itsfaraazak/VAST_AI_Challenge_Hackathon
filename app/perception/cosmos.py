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

If scene="bench", return ONLY this compact JSON (double quotes, no markdown, no extra keys):
{"scene":"bench",
 "observation":"<ONE sentence, max 20 words: what is on the board and what looks wrong>",
 "components":[{"id":"nano1","type":"arduino","value":"nano"},{"id":"r1","type":"resistor","value":"220"},{"id":"d1","type":"led","value":"red"},{"id":"w1","type":"wire","value":"black"}],
 "nets":[["<partid>.<pin>","<partid>.<pin>"]],
 "led_lit":false,
 "issues":["<max 12 words each, [] if none>"]}

Rules:
- components: list EVERY visible part: the board (arduino for Nano, esp32 for ESP32), each resistor, each LED (value = color), each jumper wire (value = color). Types: resistor, led, battery, supply, switch, wire, capacitor, diode, arduino, esp32, breadboard, unknown. Max 10 components.
- nets: ONLY connections you can actually trace in the image. Pins look like nano1.d13, nano1.gnd, nano1.5v; LED anode (long leg) = d1.a, cathode (short leg) = d1.k; resistor ends r1.a / r1.b. If you cannot trace it, leave it out and mention it in issues. Never invent. The values above are only a FORMAT illustration.
- led_lit = true only if the LED is visibly glowing.
- issues: real problems you see (LED backwards, no resistor, resistor to 5V not D13, cathode not on GND, board not in breadboard, loose wire...). Never repeat a phrase. Stop when the JSON is closed.
"""


def _from_raw(text: str) -> dict:
    data = json.loads(_repair(text))
    if isinstance(data, dict):  # drop entries the model left half-written instead of failing the whole frame
        data["components"] = [c for c in (data.get("components") or []) if isinstance(c, dict) and c.get("id") and c.get("type")]
        data["nets"] = [n for n in (data.get("nets") or [])
                        if isinstance(n, list) and len(n) >= 2 and all(isinstance(e, str) and "." in e and "<" not in e for e in n)]
    issues = data.get("issues")
    if isinstance(issues, list) and not data.get("wiring_check"):
        data["wiring_check"] = {"ok": not issues, "issues": [str(i)[:140] for i in issues][:6]}
    twin = parse_twin(data)
    if twin.get("scene") == "bench" and not twin["components"]:
        raise TwinParseError("bench scene with no parts: retry")   # useless frame, ask again
    if "led_lit" in data:
        twin["led_lit"] = bool(data["led_lit"])
    return twin


def _repair(text: str) -> str:
    """Salvage truncated / single-quoted JSON from a VLM that ran into max_tokens."""
    t = (text or "").strip()
    i = t.find("{")
    if i < 0:
        return t
    t = t[i:]
    try:
        json.loads(t)
        return t
    except json.JSONDecodeError:
        pass
    # cut back to the last comma or closing bracket at depth>0, then close what is open
    for cut in range(len(t), 0, -1):
        if t[cut - 1] not in ",]}":
            continue
        cand = t[:cut].rstrip(",")
        stack, in_str, esc = [], False, False
        for ch in cand:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_str:
            continue
        try:
            json.loads(cand + "".join(reversed(stack)))
            return cand + "".join(reversed(stack))
        except json.JSONDecodeError:
            continue
    # last resort: truncated inside the final string value -> close the string and the objects
    for tail in ('"}', '"]}', '"}]}', '"}}'):
        try:
            json.loads(t + tail)
            return t + tail
        except json.JSONDecodeError:
            pass
    return t


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
        "max_tokens": 600,
        "messages": [{"role": "user", "content": content}],
    }
    text = None
    meta: dict = {"ok": False, "ms": 0, "retries": 0, "model": model, "endpoint": "chat/completions"}
    for attempt in range(3):
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
            twin = _from_raw(text)
            meta["ok"] = True
            meta["retries"] = attempt
            meta["scene"] = twin.get("scene")
            return twin, meta
        except (TwinParseError, json.JSONDecodeError, ValueError, TypeError):
            meta["retries"] = attempt + 1
            # Retry from scratch with a little randomness: continuing from the broken reply made it worse,
            # and a temperature of 0 can loop on the same wrong tokens.
            body = {
                "model": model,
                "temperature": (0.4, 0.7)[min(attempt, 1)],
                "max_tokens": 600,
                "messages": [{"role": "user", "content": content}],
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
