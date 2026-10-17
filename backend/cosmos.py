"""Cosmos3 reasoner client. Auth from env / team config only."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_HOST = "166.19.38.112"
PROMPT = (
    "You are CURRENT, a bench partner looking at one still of an Arduino electronics build. "
    "Focus on Nano/Uno, breadboard, LEDs, resistors, jumper wires, and pin headers. "
    "Reply with ONLY compact JSON (no markdown): "
    '{"board":"nano|uno|unknown","components":["..."],'
    '"wires":[{"color":"","from":"","to":""}],"pins_used":["D13","GND"],'
    '"action":"placing|wiring|idle|testing",'
    '"risks":["no_resistor_on_LED","wrong_pin","possible_short","usb_while_rewiring"],'
    '"summary":"one sentence of what you see",'
    '"placement_advice":"one concrete next placement tip for LED/resistor/jumpers"}'
)


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


class CosmosError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class CosmosClient:
    def __init__(self) -> None:
        host = _env("GPU_HOST") or DEFAULT_HOST
        self.base = (_env("COSMOS3_REASON_URL") or f"http://{host}:8001").rstrip("/")
        self.token = _env("GPU_BEARER_TOKEN")
        self.model = _env("COSMOS3_REASON_MODEL")
        self._model_ready = bool(self.model)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def ensure_model(self) -> str:
        if self._model_ready and self.model:
            return self.model
        request = urllib.request.Request(
            self.base + "/v1/models",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
            raise CosmosError("Cosmos models endpoint failed", 502) from exc
        data = body.get("data") if isinstance(body, dict) else None
        if not data:
            raise CosmosError("Cosmos returned no models", 502)
        self.model = data[0].get("id") or "nvidia/cosmos3-reason"
        self._model_ready = True
        return self.model

    def reason_image(self, jpeg_b64: str, extra: str = "") -> dict:
        model = self.ensure_model()
        text = PROMPT if not extra else PROMPT + "\n" + extra
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 280,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"},
                        },
                    ],
                }
            ],
        }
        request = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
            raise CosmosError("Cosmos reason call failed", 502) from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CosmosError("Cosmos response missing content", 502) from exc
        if not isinstance(content, str) or not content.strip():
            raise CosmosError("Cosmos returned empty content", 502)
        return _parse_jsonish(content)


def _parse_jsonish(text: str) -> dict:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {
        "board": "unknown",
        "components": [],
        "wires": [],
        "pins_used": [],
        "action": "idle",
        "risks": [],
        "summary": cleaned[:400],
        "placement_advice": "",
    }
