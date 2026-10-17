"""Live bench session: camera frames → Cosmos. VAST captions only for chat few-shot."""

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
STREAK_NEEDED = 2
# If the board is already partly built, catch up in one confident look.
CATCHUP_CONFIDENCE = 0.55

# Structured evidence required before a step can complete.
STEP_EVIDENCE = {
    "led": ("led",),
    "resistor": ("resistor",),
    "signal": ("jumper", "wire", "d13", "pin 13", "pin13"),
    "gnd": ("gnd", "ground"),
    "flash": ("usb", "blink", "upload", "ide"),
}


class LiveSession:
    def __init__(self, vss_client: vss.VssClient, cosmos_client: cosmos.CosmosClient) -> None:
        self.vss = vss_client
        self.cosmos = cosmos_client
        self._lock = threading.Lock()
        self.done = {step["id"]: False for step in rules.STEPS}
        self.resistor_seen = False
        self.usb_connected = False
        self.warn_at: dict[str, float] = {}
        self.streak = {step["id"]: 0 for step in rules.STEPS}
        self.notes: list[dict] = []
        self.last_caption = ""
        self.last_advice = ""
        self.last_raw: dict = {}
        self.examples: list[str] = []
        self._examples_loaded = False
        self.started = time.time()
        self.frames_seen = 0
        self.frames_reliable = 0

    def public(self) -> dict:
        with self._lock:
            return {
                "mode": "live",
                "steps": self._steps(),
                "caption": self.last_caption,
                "advice": self.last_advice,
                "circuit": self._circuit(),
                "example_count": len(self.examples),
                "frames_seen": self.frames_seen,
                "frames_reliable": self.frames_reliable,
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
            rows.append(
                {
                    "id": step["id"],
                    "title": step["title"],
                    "state": state,
                    "streak": self.streak.get(step["id"], 0),
                    "need": STREAK_NEEDED,
                }
            )
        return rows

    def _circuit(self) -> dict:
        if not self.notes:
            return {"components": [], "connections": []}
        note = self.notes[-1]
        return {"components": note.get("components") or [], "connections": note.get("connections") or []}

    def _ensure_examples(self) -> None:
        """VAST examples are for chat only — never for vision."""
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

    @staticmethod
    def _norm_list(values: object) -> list[str]:
        if not isinstance(values, list):
            return []
        return [str(v).strip().lower() for v in values if str(v).strip()]

    def _frame_is_reliable(self, raw: dict) -> bool:
        visible = raw.get("visible_electronics")
        comps = self._norm_list(raw.get("components"))
        board = str(raw.get("board") or "unknown").lower()
        summary = str(raw.get("summary") or "").lower()
        try:
            confidence = float(raw.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0

        # Explicit false only wins if there is also no component evidence
        if visible is False and not comps and board == "unknown":
            # still allow keyword recovery from summary
            if not any(
                w in summary
                for w in ("arduino", "nano", "breadboard", "led", "resistor", "jumper")
            ):
                return False

        if comps or board in {"nano", "uno"}:
            return True
        if visible is True:
            return True
        if any(w in summary for w in ("arduino", "nano", "breadboard", "led", "resistor")):
            return True
        return confidence >= 0.5 and visible is not False

    def _support_from_structure(self, raw: dict) -> dict[str, bool]:
        comps = self._norm_list(raw.get("components"))
        pins = self._norm_list(raw.get("pins_used"))
        wires = raw.get("wires") if isinstance(raw.get("wires"), list) else []
        wire_blob = " ".join(
            f"{w.get('color', '')} {w.get('from', '')} {w.get('to', '')}"
            for w in wires
            if isinstance(w, dict)
        ).lower()
        blob = " ".join(comps + pins) + " " + wire_blob
        support = {step["id"]: False for step in rules.STEPS}
        for sid, needles in STEP_EVIDENCE.items():
            support[sid] = any(n in blob for n in needles)
        # signal needs a pin or a wire endpoint that looks like D13 / pin 13
        if not support["signal"]:
            support["signal"] = any(
                p.replace(" ", "") in {"d13", "pin13", "13"} or p.endswith("13") for p in pins
            )
        return support

    def analyze_frame(self, jpeg_b64: str) -> dict:
        # Vision call: image only — no VAST text (that caused fake Arduino detections)
        try:
            raw = self.cosmos.reason_image(jpeg_b64)
        except cosmos.CosmosError as exc:
            raise vss.VssError(str(exc), getattr(exc, "status", 502)) from exc

        summary = str(raw.get("summary") or "").strip()
        advice = str(raw.get("placement_advice") or "").strip()
        reliable = self._frame_is_reliable(raw)
        now = time.time() - self.started

        with self._lock:
            self.frames_seen += 1
            alerts: list[dict] = []

            if not reliable:
                # reset streaks — empty desk must not keep progress cooking
                for sid in self.streak:
                    if not self.done[sid]:
                        self.streak[sid] = 0
                self.last_caption = summary or "No clear electronics in frame."
                self.last_advice = ""
                self.last_raw = raw
                return {
                    "steps": self._steps(),
                    "alerts": [],
                    "caption": self.last_caption,
                    "advice": "",
                    "circuit": self._circuit(),
                    "reliable": False,
                    "raw": {
                        "board": raw.get("board"),
                        "components": raw.get("components") or [],
                        "pins_used": raw.get("pins_used") or [],
                        "risks": raw.get("risks") or [],
                        "confidence": raw.get("confidence"),
                        "visible_electronics": raw.get("visible_electronics"),
                    },
                }

            self.frames_reliable += 1
            support = self._support_from_structure(raw)
            comps = " ".join(self._norm_list(raw.get("components")))
            pins = " ".join(self._norm_list(raw.get("pins_used")))
            blob = f"{summary} {comps} {pins}"

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
                if key == "no_resistor_on_LED" and support["led"] and not support["resistor"]:
                    alerts.append(
                        {
                            "severity": "warning",
                            "text": "LED visible without a clear resistor. Add 220Ω before powering.",
                            "speak": True,
                        }
                    )
                elif key == "wrong_pin" and not self.done["signal"]:
                    alerts.append(
                        {
                            "severity": "warning",
                            "text": "Signal pin does not look like D13. Blink expects D13.",
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
            if rules.usb_is_connected(blob) or "usb" in self._norm_list(raw.get("components")):
                self.usb_connected = True

            try:
                confidence = float(raw.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0

            # Catch-up: one confident look can verify every already-done physical step
            if confidence >= CATCHUP_CONFIDENCE or len(self._norm_list(raw.get("components"))) >= 3:
                for step in rules.STEPS:
                    sid = step["id"]
                    if self.done[sid]:
                        continue
                    if support.get(sid):
                        self.done[sid] = True
                        self.streak[sid] = STREAK_NEEDED
                        alerts.append(
                            {
                                "severity": "info",
                                "text": f"Verified step: {step['title']}",
                                "speak": False,
                            }
                        )
                    else:
                        break
            else:
                # Cautious path: only the next open step, needs two agreeing frames
                for step in rules.STEPS:
                    sid = step["id"]
                    if self.done[sid]:
                        continue
                    if support.get(sid):
                        self.streak[sid] = self.streak.get(sid, 0) + 1
                    else:
                        self.streak[sid] = 0
                    if self.streak[sid] >= STREAK_NEEDED:
                        self.done[sid] = True
                        alerts.append(
                            {
                                "severity": "info",
                                "text": f"Verified step: {step['title']}",
                                "speak": False,
                            }
                        )
                    break

            note = rules.merge_circuit(
                self.notes[-1] if self.notes else None,
                rules.circuit_from_caption(blob),
            )
            note = dict(note)
            note["at_sec"] = now
            self.notes.append(note)
            self.last_caption = summary
            self.last_advice = advice if reliable else ""
            self.last_raw = raw

            seen_text: set[str] = set()
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
                "advice": self.last_advice,
                "circuit": {"components": note["components"], "connections": note["connections"][:8]},
                "reliable": True,
                "raw": {
                    "board": raw.get("board"),
                    "components": raw.get("components") or [],
                    "pins_used": raw.get("pins_used") or [],
                    "risks": raw.get("risks") or [],
                    "confidence": raw.get("confidence"),
                    "visible_electronics": raw.get("visible_electronics"),
                    "streak": {k: self.streak[k] for k in self.streak},
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
            reliable = self._frame_is_reliable(raw) if raw else False

        if not reliable and not caption:
            return {
                "answer": "I have not seen a clear Arduino bench yet. Point Desk View at the breadboard and wait for a verified look.",
                "seek_sec": None,
                "evidence_summary": "no-reliable-frame",
            }

        try:
            examples.extend(self.vss.search_captions(message[:120], "electronics-bench-nano", top_k=4))
            examples.extend(self.vss.search_captions(message[:120], "electronics-bench", top_k=4))
        except vss.VssError:
            pass
        seen: set[str] = set()
        deduped: list[str] = []
        for text in examples:
            key = text[:80]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)
        examples = deduped[:8]

        phrased = _phrase(message, caption, advice, circuit, examples, raw, reliable)
        if not phrased:
            if advice and reliable:
                phrased = advice
            elif caption:
                phrased = f"From the last verified look: {caption}"
            else:
                phrased = "Show the board clearly and ask again."
        return {
            "answer": phrased,
            "seek_sec": None,
            "evidence_summary": f"reliable={reliable} examples={len(examples)}",
        }


def _phrase(
    message: str,
    caption: str,
    advice: str,
    circuit: dict,
    examples: list[str],
    raw: dict,
    reliable: bool,
) -> str | None:
    key = os.environ.get("WANDB_API_KEY", "").strip()
    if not key:
        return None
    lines = [
        f"Live vision reliable: {reliable}",
        f"Live board summary: {caption or 'none yet'}",
        f"Placement advice from vision: {advice or 'none'}",
        f"Structured: {json.dumps(raw)[:700]}",
        "Components: " + (", ".join(circuit.get("components") or []) or "none"),
        "Connections: " + ("; ".join((circuit.get("connections") or [])[:4]) or "none"),
    ]
    if examples:
        lines.append("Indexed Arduino examples from VAST (prior demos only, not this camera):")
        for ex in examples[:5]:
            lines.append(f"- {ex}")
    payload = {
        "model": WAND_MODEL,
        "temperature": 0.1,
        "max_tokens": 140,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are CURRENT, an Arduino bench partner. "
                    "Trust the live vision fields first. If reliable is false, say you cannot see the board yet. "
                    "VAST examples are style only. One or two short sentences. No markdown."
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
