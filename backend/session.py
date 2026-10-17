"""Live bench session: camera frames → Cosmos, VAST captions as few-shot examples."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

import cosmos
import rules
import vss

WAND_BASE = "https://api.inference.wandb.ai/v1"
WAND_MODEL = "meta-llama/Llama-3.1-8B-Instruct"


class LiveSession:
    def __init__(self, vss_client: vss.VssClient, cosmos_client: cosmos.CosmosClient) -> None:
        self.vss = vss_client
        self.cosmos = cosmos_client
        self._lock = threading.Lock()
        self.done = {step["id"]: False for step in rules.STEPS}
        self.resistor_seen = False
        self.usb_connected = False
        self.warn_at: dict[str, float] = {}
        self.last_support = {step["id"]: False for step in rules.STEPS}
        self.streak = {step["id"]: 0 for step in rules.STEPS}
        self.notes: list[dict] = []
        self.last_caption = ""
        self.last_advice = ""
        self.last_raw: dict = {}
        self.examples: list[str] = []
        self._examples_loaded = False
        self.started = time.time()

    def public(self) -> dict:
        self._ensure_examples()
        with self._lock:
            return {
                "mode": "live",
                "steps": self._steps(),
                "caption": self.last_caption,
                "advice": self.last_advice,
                "circuit": self._circuit(),
                "example_count": len(self.examples),
            }

    def _steps(self) -> list[dict]:
        rows = []
        active_set = False
        for step in rules.STEPS:
            if self.done[step["id"]]:
                state = "done"
            elif not active_set:
                state = "active"
                active_set = True
            else:
                state = "pending"
            rows.append({"id": step["id"], "title": step["title"], "state": state})
        return rows

    def _circuit(self) -> dict:
        if not self.notes:
            return {"components": [], "connections": []}
        note = self.notes[-1]
        return {"components": note.get("components") or [], "connections": note.get("connections") or []}

    def _ensure_examples(self) -> None:
        if self._examples_loaded:
            return
        with self._lock:
            if self._examples_loaded:
                return
            excerpts: list[str] = []
            for location, query in (
                ("electronics-bench-nano", "Arduino Nano breadboard LED resistor jumper"),
                ("electronics-bench", "Arduino breadboard LED resistor jumper wiring"),
            ):
                try:
                    excerpts.extend(self.vss.search_captions(query, location, top_k=6))
                except vss.VssError:
                    continue
            # de-dupe preserve order
            seen: set[str] = set()
            unique: list[str] = []
            for text in excerpts:
                key = text[:80]
                if key in seen:
                    continue
                seen.add(key)
                unique.append(text)
            self.examples = unique[:8]
            self._examples_loaded = True

    def analyze_frame(self, jpeg_b64: str) -> dict:
        self._ensure_examples()
        extra = ""
        if self.examples:
            extra = "Prior indexed bench examples (style reference only):\n- " + "\n- ".join(self.examples[:4])
        try:
            raw = self.cosmos.reason_image(jpeg_b64, extra=extra)
        except cosmos.CosmosError as exc:
            raise vss.VssError(str(exc), getattr(exc, "status", 502)) from exc

        summary = str(raw.get("summary") or "").strip()
        advice = str(raw.get("placement_advice") or "").strip()
        caption = summary
        if advice:
            caption = f"{summary} Advice: {advice}".strip()

        now = time.time() - self.started
        with self._lock:
            support = rules.support_map(caption)
            # also mark from structured fields
            comps = " ".join(str(x) for x in (raw.get("components") or []))
            pins = " ".join(str(x) for x in (raw.get("pins_used") or []))
            blob = f"{caption} {comps} {pins}"
            support = {
                key: support[key] or rules.mentions(blob, rules.SUPPORT[key]) for key in support
            }
            alerts = rules.warnings_for(
                blob,
                now,
                resistor_seen=self.resistor_seen,
                usb_connected=self.usb_connected,
                signal_open=not self.done["signal"],
                last_warn_at=self.warn_at,
            )
            for risk in raw.get("risks") or []:
                key = str(risk)
                if key == "no_resistor_on_LED" and not self.resistor_seen:
                    alerts.append(
                        {
                            "severity": "warning",
                            "text": "Cosmos sees an LED without a clear resistor. Add 220Ω before powering.",
                            "speak": True,
                        }
                    )
                elif key == "wrong_pin":
                    alerts.append(
                        {
                            "severity": "warning",
                            "text": "Pin look wrong for Blink — sketch expects D13.",
                            "speak": True,
                        }
                    )
                elif key == "usb_while_rewiring":
                    alerts.append(
                        {
                            "severity": "warning",
                            "text": "Rewiring while powered. Unplug USB first.",
                            "speak": True,
                        }
                    )

            if support["resistor"]:
                self.resistor_seen = True
            if rules.usb_is_connected(blob):
                self.usb_connected = True

            for step in rules.STEPS:
                sid = step["id"]
                if self.done[sid]:
                    continue
                if support.get(sid):
                    self.streak[sid] = self.streak.get(sid, 0) + 1
                else:
                    self.streak[sid] = 0
            # sequential completion: mark next open step if supported
            for step in rules.STEPS:
                sid = step["id"]
                if self.done[sid]:
                    continue
                if self.streak.get(sid, 0) >= 1:
                    self.done[sid] = True
                break

            note = rules.merge_circuit(
                self.notes[-1] if self.notes else None,
                rules.circuit_from_caption(blob),
            )
            note = dict(note)
            note["at_sec"] = now
            if raw.get("wires"):
                for wire in raw["wires"][:4]:
                    if isinstance(wire, dict):
                        line = f"{wire.get('color', '')} {wire.get('from', '')}->{wire.get('to', '')}".strip()
                        if line and line not in note["connections"]:
                            note["connections"].append(line)
            self.notes.append(note)
            self.last_caption = summary
            self.last_advice = advice
            self.last_raw = raw
            self.last_support = support

            # dedupe alerts by text
            seen_text = set()
            unique = []
            for alert in alerts:
                text = alert.get("text") or ""
                if text in seen_text:
                    continue
                seen_text.add(text)
                unique.append(alert)

            return {
                "steps": self._steps(),
                "alerts": unique[:3],
                "caption": summary,
                "advice": advice,
                "circuit": {"components": note["components"], "connections": note["connections"][:8]},
                "raw": {
                    "board": raw.get("board"),
                    "pins_used": raw.get("pins_used") or [],
                    "risks": raw.get("risks") or [],
                },
            }

    def chat(self, message: str) -> dict:
        self._ensure_examples()
        with self._lock:
            caption = self.last_caption
            advice = self.last_advice
            circuit = self._circuit()
            examples = list(self.examples[:5])
            raw = dict(self.last_raw)

        # Pull fresh similar moments from VAST for this question
        try:
            examples.extend(self.vss.search_captions(message[:120], "electronics-bench-nano", top_k=4))
            examples.extend(self.vss.search_captions(message[:120], "electronics-bench", top_k=4))
        except vss.VssError:
            pass
        # de-dupe
        seen: set[str] = set()
        deduped: list[str] = []
        for text in examples:
            key = text[:80]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)
        examples = deduped[:8]

        phrased = _phrase(message, caption, advice, circuit, examples, raw)
        if not phrased:
            # fallback without W&B
            bits = []
            if advice:
                bits.append(advice)
            if caption:
                bits.append(f"I currently see: {caption}")
            if not bits:
                bits.append("Arm the camera and let me look once, then ask again.")
            phrased = " ".join(bits)
        return {"answer": phrased, "seek_sec": None, "evidence_summary": f"cosmos+live examples={len(examples)}"}


def _phrase(
    message: str,
    caption: str,
    advice: str,
    circuit: dict,
    examples: list[str],
    raw: dict,
) -> str | None:
    key = os.environ.get("WANDB_API_KEY", "").strip()
    if not key:
        return None
    lines = [
        f"Live board summary: {caption or 'none yet'}",
        f"Placement advice from vision: {advice or 'none'}",
        f"Structured: {json.dumps(raw)[:700]}",
        "Components: " + (", ".join(circuit.get("components") or []) or "none"),
        "Connections: " + ("; ".join((circuit.get("connections") or [])[:4]) or "none"),
    ]
    if examples:
        lines.append("Indexed Arduino examples from VAST (treat as prior demos, not this camera):")
        for ex in examples[:5]:
            lines.append(f"- {ex}")
    payload = {
        "model": WAND_MODEL,
        "temperature": 0.2,
        "max_tokens": 160,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are CURRENT, a fast Arduino bench partner. "
                    "Give concrete placement guidance for LEDs, resistors, and jumper wires. "
                    "Use the live vision summary first, then the VAST examples for style. "
                    "One or two short sentences. No markdown."
                ),
            },
            {"role": "user", "content": "Question: " + message.strip() + "\n\n" + "\n".join(lines)},
        ],
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    team = os.environ.get("WANDB_TEAM", "").strip()
    project = os.environ.get("WANDB_PROJECT", "").strip()
    if team and project:
        headers["OpenAI-Project"] = f"{team}/{project}"
    text = _wandb_call(payload, headers)
    if text:
        return text
    if "OpenAI-Project" in headers:
        headers.pop("OpenAI-Project", None)
        return _wandb_call(payload, headers)
    return None


def _wandb_call(payload: dict, headers: dict) -> str | None:
    request = urllib.request.Request(
        WAND_BASE + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = json.loads(response.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, ValueError):
        return None
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str):
        return None
    return content.strip() or None
