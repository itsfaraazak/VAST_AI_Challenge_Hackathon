"""Cosmos3 reasoner client. Auth from env / team config only."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_HOST = "166.19.38.112"
PROMPT = (
    "Look only at this image. If you clearly see an Arduino, breadboard, LED, resistor, "
    "jumper wire, or USB cable, set visible_electronics=true and list them. "
    "If the frame is empty desk/keyboard with no parts, set visible_electronics=false. "
    "Do not invent parts. Reply with ONE JSON object only, no markdown fences: "
    '{"visible_electronics":true,'
    '"board":"nano",'
    '"components":["breadboard","LED","resistor","jumper","usb"],'
    '"pins_used":["D13","GND"],'
    '"action":"wiring",'
    '"risks":[],'
    '"confidence":0.8,'
    '"summary":"short description",'
    '"placement_advice":"one tip"}'
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

    def reason_image(self, jpeg_b64: str) -> dict:
        model = self.ensure_model()
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 450,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
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
            with urllib.request.urlopen(request, timeout=60) as response:
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


def _repair_truncated(text: str) -> str:
    """Best-effort close of truncated JSON objects/arrays/strings."""
    s = text.rstrip()
    if not s.startswith("{"):
        return s
    # close an open string
    if s.count('"') % 2 == 1:
        s += '"'
    opens = s.count("{") - s.count("}")
    opens_arr = s.count("[") - s.count("]")
    s += "]" * max(0, opens_arr)
    s += "}" * max(0, opens)
    return s


def _parse_jsonish(text: str) -> dict:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    # strip leading ```json without closing fence (truncated reply)
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned).strip()

    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0:
        if end > start:
            candidates.append(cleaned[start : end + 1])
        candidates.append(_repair_truncated(cleaned[start:]))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and (
            "visible_electronics" in data or "components" in data or "board" in data
        ):
            return _normalize(data)

    # Last resort: keyword sniff from free text so we don't hard-fail a good look
    low = text.lower()
    comps = []
    for name in ("breadboard", "led", "resistor", "jumper", "usb", "arduino", "nano"):
        if name in low:
            comps.append("LED" if name == "led" else name)
    if comps:
        return {
            "visible_electronics": True,
            "board": "nano" if "nano" in low else ("uno" if "uno" in low else "unknown"),
            "components": comps,
            "wires": [],
            "pins_used": [],
            "action": "wiring",
            "risks": [],
            "confidence": 0.55,
            "summary": re.sub(r"\s+", " ", text)[:240],
            "placement_advice": "",
        }

    return {
        "visible_electronics": False,
        "board": "unknown",
        "components": [],
        "wires": [],
        "pins_used": [],
        "action": "none",
        "risks": [],
        "confidence": 0.0,
        "summary": re.sub(r"\s+", " ", text)[:400],
        "placement_advice": "",
    }


def _normalize(data: dict) -> dict:
    comps = data.get("components") or []
    if not isinstance(comps, list):
        comps = []
    visible = data.get("visible_electronics")
    if visible is None:
        visible = bool(comps) or str(data.get("board") or "").lower() in {"nano", "uno"}
    try:
        confidence = float(data.get("confidence") or (0.7 if visible else 0.0))
    except (TypeError, ValueError):
        confidence = 0.7 if visible else 0.0
    return {
        "visible_electronics": bool(visible),
        "board": data.get("board") or "unknown",
        "components": comps,
        "wires": data.get("wires") if isinstance(data.get("wires"), list) else [],
        "pins_used": data.get("pins_used") if isinstance(data.get("pins_used"), list) else [],
        "action": data.get("action") or "none",
        "risks": data.get("risks") if isinstance(data.get("risks"), list) else [],
        "confidence": confidence,
        "summary": str(data.get("summary") or "").strip(),
        "placement_advice": str(data.get("placement_advice") or "").strip(),
    }
