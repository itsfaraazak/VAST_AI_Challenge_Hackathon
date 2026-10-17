"""In-memory replay session: clip list, step streaks, circuit notes, grounded chat."""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

import rules
import simulator
import vss

WAND_BASE = "https://api.inference.wandb.ai/v1"
WAND_MODEL = "meta-llama/Llama-3.1-8B-Instruct"

_CHANGE = re.compile(r"what.*(change|differ|move)|what did i|what changed", re.I)
_SIM_ASK = re.compile(
    r"what should i (wire|do|build)|next (step|wire)|will it work|simulate|wokwi|sim\b|what to wire",
    re.I,
)
_TOPIC_WORDS = (
    ("resistor", re.compile(r"resistor|220", re.I), rules.SUPPORT["resistor"]),
    ("led", re.compile(r"\bleds?\b|diode", re.I), rules.SUPPORT["led"]),
    ("gnd", re.compile(r"\b(gnd|ground)\b", re.I), rules.SUPPORT["gnd"]),
    ("signal", re.compile(r"\b(d\s*13|pin|jumper|signal)\b", re.I), rules.SUPPORT["signal"]),
    ("flash", re.compile(r"\b(ide|upload|blink|sketch|flash)\b", re.I), rules.SUPPORT["flash"]),
    ("usb", re.compile(r"\busb\b", re.I), re.compile(r"\busb\b", re.I)),
)


def _clip_id(original_video: str) -> str:
    name = original_video.rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".mp4") else name


def _title(tags: list, camera_id: str) -> str:
    skip = {"cc", "retry", "youtube", "demo"}
    kept = [tag for tag in tags if str(tag).lower() not in skip]
    head = ", ".join(kept[:3]) if kept else "bench clip"
    if camera_id:
        return f"{head} · {camera_id}"
    return head


def _stream_url(original_video: str) -> str:
    return "api/videos/stream?original_video=" + urllib.parse.quote(original_video, safe="")


class ReplaySession:
    def __init__(self, client: vss.VssClient | None = None) -> None:
        self.client = client or vss.VssClient()
        self._lock = threading.Lock()
        self.ready = False
        self.clips: list[dict] = []
        self.active_video = vss.DEFAULT_VIDEO
        self.states: dict[str, dict] = {}

    def ensure(self) -> None:
        if self.ready:
            return
        with self._lock:
            if self.ready:
                return
            self._load()
            self.ready = True

    def _load(self) -> None:
        raw_clips = self.client.search_bench_clips()
        clips = []
        for raw in raw_clips:
            video = raw["original_video"]
            clips.append(
                {
                    "id": _clip_id(video),
                    "title": _title(raw.get("tags") or [], raw.get("camera_id") or ""),
                    "original_video": video,
                    "camera_id": raw.get("camera_id") or "",
                    "location": raw.get("location") or "",
                    "tags": list(raw.get("tags") or []),
                    "duration_sec": float(raw.get("duration_sec") or 0),
                }
            )
        self.clips = clips
        known = {clip["original_video"] for clip in clips}
        if vss.DEFAULT_VIDEO in known:
            self.active_video = vss.DEFAULT_VIDEO
        elif clips:
            self.active_video = clips[0]["original_video"]
        self._ensure_state(self.active_video)

    def _ensure_state(self, original_video: str) -> dict:
        state = self.states.get(original_video)
        if state:
            return state
        segments = self.client.segments(original_video)
        meta = next((clip for clip in self.clips if clip["original_video"] == original_video), None)
        if segments:
            if meta is not None:
                meta["duration_sec"] = max(seg["segment_end_sec"] for seg in segments)
                if not meta["camera_id"]:
                    meta["camera_id"] = segments[0].get("camera_id") or ""
                if not meta["location"]:
                    meta["location"] = segments[0].get("location") or ""
                if not meta["tags"]:
                    meta["tags"] = list(segments[0].get("tags") or [])
                    meta["title"] = _title(meta["tags"], meta["camera_id"])
        state = {
            "segments": segments,
            "done": {step["id"]: False for step in rules.STEPS},
            "last_number": None,
            "last_support": {},
            "seen": set(),
            "resistor_seen": False,
            "usb_connected": False,
            "warn_at": {},
            "notes": [],
        }
        self.states[original_video] = state
        return state

    def _steps(self, state: dict) -> list[dict]:
        active_set = False
        view = []
        for step in rules.STEPS:
            if state["done"][step["id"]]:
                status = "done"
            elif not active_set:
                status = "active"
                active_set = True
            else:
                status = "pending"
            view.append({"id": step["id"], "title": step["title"], "state": status})
        return view

    def _summary(self, state: dict) -> list[dict]:
        rows = []
        for seg in state["segments"]:
            caption = re.sub(r"\s+", " ", seg["reasoning_content"]).strip()
            if len(caption) > 160:
                caption = caption[:157] + "..."
            rows.append(
                {
                    "segment_number": seg["segment_number"],
                    "segment_start_sec": seg["segment_start_sec"],
                    "caption": caption,
                }
            )
        return rows

    def _circuit(self, state: dict) -> dict:
        if not state["notes"]:
            return {"components": [], "connections": []}
        latest = state["notes"][-1]
        return {"components": list(latest["components"]), "connections": list(latest["connections"])}

    def circuit_for(self, original_video: str | None) -> dict:
        self.ensure()
        with self._lock:
            video = original_video or self.active_video
            if video not in {clip["original_video"] for clip in self.clips}:
                raise vss.VssError("clip is not in the bench list", 404)
            state = self._ensure_state(video)
            return self._circuit(state)

    def public(self) -> dict:
        self.ensure()
        with self._lock:
            state = self._ensure_state(self.active_video)
            active = next(clip for clip in self.clips if clip["original_video"] == self.active_video)
            return {
                "clips": self.clips,
                "active_id": active["id"],
                "stream_url": _stream_url(self.active_video),
                "steps": self._steps(state),
                "segments": self._summary(state),
            }

    def select(self, original_video: str) -> dict:
        self.ensure()
        with self._lock:
            known = {clip["original_video"] for clip in self.clips}
            if original_video not in known:
                raise vss.VssError("clip is not in the bench list", 404)
            self.active_video = original_video
            self._ensure_state(original_video)
        return self.public()

    def _segment_at(self, state: dict, time_sec: float) -> dict | None:
        chosen = None
        for seg in state["segments"]:
            if seg["segment_start_sec"] <= time_sec + 0.05:
                chosen = seg
            else:
                break
        return chosen

    def tick(self, original_video: str, time_sec: float) -> dict:
        self.ensure()
        with self._lock:
            if original_video not in {clip["original_video"] for clip in self.clips}:
                raise vss.VssError("clip is not in the bench list", 404)
            self.active_video = original_video
            state = self._ensure_state(original_video)
            seg = self._segment_at(state, time_sec)
            if seg is None:
                return {
                    "segment_number": None,
                    "caption": "",
                    "steps": self._steps(state),
                    "alerts": [],
                    "circuit": self._circuit(state),
                }
            number = seg["segment_number"]
            if number in state["seen"]:
                return {
                    "segment_number": number,
                    "caption": seg["reasoning_content"],
                    "steps": self._steps(state),
                    "alerts": [],
                    "circuit": self._circuit(state),
                }
            caption = seg["reasoning_content"]
            support = rules.support_map(caption)
            alerts = rules.warnings_for(
                caption,
                float(seg["segment_start_sec"]),
                resistor_seen=state["resistor_seen"],
                usb_connected=state["usb_connected"],
                signal_open=not state["done"]["signal"],
                last_warn_at=state["warn_at"],
            )
            if support["resistor"]:
                state["resistor_seen"] = True
            if rules.usb_is_connected(caption):
                state["usb_connected"] = True
            previous = state["last_number"]
            previous_support = state["last_support"]
            if previous is not None and number == previous + 1:
                for step in rules.STEPS:
                    step_id = step["id"]
                    if state["done"][step_id]:
                        continue
                    if previous_support.get(step_id) and support.get(step_id):
                        state["done"][step_id] = True
            state["last_number"] = number
            state["last_support"] = support
            state["seen"].add(number)
            note = rules.merge_circuit(state["notes"][-1] if state["notes"] else None, rules.circuit_from_caption(caption))
            note = dict(note)
            note["at_sec"] = seg["segment_start_sec"]
            state["notes"].append(note)
            circuit = {"components": note["components"], "connections": note["connections"]}
            sim_hint = None
            if alerts:
                advice = simulator.advise(circuit, question="warning")
                if advice.get("next_actions"):
                    sim_hint = advice["advice"]
            return {
                "segment_number": number,
                "caption": caption,
                "steps": self._steps(state),
                "alerts": alerts,
                "circuit": circuit,
                "sim_hint": sim_hint,
            }

    def _excerpts(self, state: dict, message: str) -> tuple[float | None, list[dict]]:
        if _CHANGE.search(message) and len(state["notes"]) >= 2:
            seek = float(state["notes"][-1]["at_sec"])
        else:
            seek = None
        patterns = []
        for _name, words, pattern in _TOPIC_WORDS:
            if words.search(message):
                patterns.append(pattern)
        hits = []
        if patterns:
            for seg in state["segments"]:
                caption = seg["reasoning_content"]
                if any(rules.mentions(caption, pattern) for pattern in patterns):
                    hits.append(seg)
        if seek is None and hits:
            seek = float(hits[0]["segment_start_sec"])
        excerpts = []
        for seg in hits[:3]:
            caption = re.sub(r"\s+", " ", seg["reasoning_content"]).strip()
            excerpts.append({"at_sec": seg["segment_start_sec"], "caption": caption[:420]})
        return seek, excerpts

    def chat(self, original_video: str, message: str) -> dict:
        self.ensure()
        with self._lock:
            if original_video not in {clip["original_video"] for clip in self.clips}:
                raise vss.VssError("clip is not in the bench list", 404)
            self.active_video = original_video
            state = self._ensure_state(original_video)
            seek, excerpts = self._excerpts(state, message)
            diff = ""
            if _CHANGE.search(message):
                older = state["notes"][-2] if len(state["notes"]) >= 2 else None
                newer = state["notes"][-1] if state["notes"] else None
                diff = rules.diff_notes(older, newer)
            circuit = self._circuit(state)
        sim_payload = None
        if _SIM_ASK.search(message):
            sim_payload = simulator.advise(circuit, question=message)
        try:
            agent = self.client.ask(message, original_video)
        except vss.VssError:
            agent = {"answer": "", "tool_used": "", "evidence": {}}
        phrased = _phrase(
            message,
            agent.get("answer") or "",
            excerpts,
            diff,
            circuit,
            seek,
            sim_payload,
        )
        if phrased:
            answer = phrased
            if seek is not None and str(int(seek)) not in answer:
                answer = answer.rstrip() + f" That shows up at {int(seek)} seconds."
        elif sim_payload and sim_payload.get("advice"):
            answer = sim_payload["advice"]
        else:
            answer = agent.get("answer") or "I could not read that moment from this clip."
        evidence = agent.get("evidence") if isinstance(agent.get("evidence"), dict) else {}
        summary = (agent.get("answer") or "").strip().replace("\n", " ")
        if len(summary) > 240:
            summary = summary[:237] + "..."
        tool = agent.get("tool_used") or "none"
        evidence_summary = f"{tool}: {summary}" if summary else tool
        if seek is not None:
            evidence_summary = f"{evidence_summary} Caption-grounded seek {int(seek)}s."
        if evidence.get("segment_count"):
            evidence_summary = f"{evidence_summary} Segments used {evidence.get('segments_used')} of {evidence.get('segment_count')}."
        if sim_payload:
            evidence_summary = f"{evidence_summary} Sim: {sim_payload.get('advice', '')}".strip()
        return {
            "answer": answer,
            "seek_sec": seek,
            "evidence_summary": evidence_summary.strip(),
            "sim": sim_payload,
        }


def _phrase(
    message: str,
    agent_answer: str,
    excerpts: list[dict],
    diff: str,
    circuit: dict,
    seek: float | None,
    sim_payload: dict | None = None,
) -> str | None:
    key = os.environ.get("WANDB_API_KEY", "").strip()
    if not key:
        return None
    lines = []
    if seek is not None:
        lines.append(f"Grounded time you may mention: {int(seek)} seconds. Do not mention any other timestamp.")
    else:
        lines.append("No grounded timestamp. Do not invent one.")
    if excerpts:
        lines.append("Caption excerpts (trust these over agent QA if they conflict):")
        for item in excerpts:
            lines.append(f"- {int(item['at_sec'])}s: {item['caption']}")
    else:
        lines.append("No caption excerpt matched the question.")
    if diff:
        lines.append("Circuit-note diff: " + diff)
    if circuit.get("components") or circuit.get("connections"):
        lines.append("Current circuit note components: " + ", ".join(circuit.get("components") or []) or "none")
    if sim_payload:
        lines.append("Electrical sim advice (quote this for wiring / will-it-work questions):")
        lines.append(sim_payload.get("advice") or "")
        for action in (sim_payload.get("next_actions") or [])[:2]:
            lines.append(f"- next: {action.get('label')}")
    if agent_answer:
        lines.append("Agent QA answer, cite it but do not repeat claims the excerpts contradict:")
        lines.append(agent_answer[:1800])
    payload = {
        "model": WAND_MODEL,
        "temperature": 0,
        "max_tokens": 180,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are CURRENT, a bench partner watching one indexed Arduino clip. "
                    "Phrase a reply in one or two short sentences using only the evidence. "
                    "If sim advice is present for a wiring or will-it-work question, lead with it. "
                    "If a grounded time is provided, mention that number of seconds. "
                    "Do not invent components, mistakes, or moments that the evidence does not state. "
                    "If the evidence does not answer, say that moment is not in this clip."
                ),
            },
            {"role": "user", "content": "Question: " + message.strip() + "\n\n" + "\n".join(lines)},
        ],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
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
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, ValueError):
        return None
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str):
        return None
    cleaned = content.strip()
    return cleaned or None
