"""Proactive teacher: curriculum + twin + W&B conversation."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from config import settings
from curriculum import get_project, infer_step_from_twin, list_projects, step_at

log = logging.getLogger("coach")

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore


async def _wandb_chat(http: aiohttp.ClientSession, system: str, user: str) -> tuple[str, dict]:
    from guidance import list_and_pick_model

    meta: dict[str, Any] = {"ms": 0, "model": None, "source": "policy"}
    model = await list_and_pick_model(http)
    if not model or not settings.wandb_ready:
        return "", meta
    meta["model"] = model
    headers = {
        "Authorization": f"Bearer {settings.wandb_key}",
        "Content-Type": "application/json",
        "OpenAI-Project": f"{settings.wandb_team}/{settings.wandb_project}",
    }
    payload = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": 220,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    t0 = time.perf_counter()
    try:
        async with http.post(
            settings.wandb_base + "/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as resp:
            data = await resp.json()
            meta["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status >= 400:
                return "", meta
            text = data["choices"][0]["message"]["content"].strip()
            meta["source"] = "wandb"
            return text, meta
    except Exception:  # noqa: BLE001
        meta["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return "", meta


def ensure_session_coach(sess) -> None:
    if getattr(sess, "coach", None) is None:
        sess.coach = {
            "phase": "ask_project",
            "project_id": None,
            "step_index": 0,
            "last_tip_key": None,
            "intro_sent": False,
        }


def public_coach_state(sess) -> dict:
    ensure_session_coach(sess)
    c = sess.coach
    project = get_project(c["project_id"]) if c.get("project_id") else None
    step = step_at(project, c["step_index"]) if project else None
    steps_public = None
    if project:
        steps_public = [
            {
                "id": s["id"],
                "title": s["title"],
                "teach": s.get("teach"),
                "action": s.get("action"),
                "pins": s.get("pins"),
                "wires": s.get("wires"),
            }
            for s in project["steps"]
        ]
    return {
        "phase": c["phase"],
        "project_id": c.get("project_id"),
        "step_index": c["step_index"],
        "step_total": len(project["steps"]) if project else 0,
        "project": (
            {"id": project["id"], "title": project["title"], "pitch": project["pitch"], "sketch": project.get("sketch")}
            if project else None
        ),
        "step": step,
        "steps": steps_public,
        "projects": list_projects(),
    }


def start_project(sess, project_id: str = "blink") -> dict:
    ensure_session_coach(sess)
    project = get_project(project_id) or get_project("blink")
    sess.coach.update({
        "phase": "teaching",
        "project_id": project["id"],
        "step_index": 0,
        "last_tip_key": None,
        "intro_sent": False,
    })
    return public_coach_state(sess)


def advance_step(sess, delta: int = 1) -> dict:
    ensure_session_coach(sess)
    project = get_project(sess.coach.get("project_id") or "blink")
    if not project:
        return public_coach_state(sess)
    n = len(project["steps"])
    sess.coach["step_index"] = max(0, min(n - 1, sess.coach["step_index"] + delta))
    sess.coach["last_tip_key"] = None
    return public_coach_state(sess)


def set_step(sess, index: int) -> dict:
    ensure_session_coach(sess)
    project = get_project(sess.coach.get("project_id") or "blink")
    if project:
        sess.coach["step_index"] = max(0, min(len(project["steps"]) - 1, index))
        sess.coach["last_tip_key"] = None
    return public_coach_state(sess)


def _fallback_tip(step: dict) -> str:
    return f"{step['concept']} {step['action']} {step['teach']}"


def ask_project_opener() -> str:
    return (
        "What would you like to build on the breadboard? "
        "For this demo, say “Blink” and we’ll wire an external LED on Arduino Nano: "
        "D13 → 220Ω → LED anode, cathode → GND."
    )


async def teach_current_step(sess, http: aiohttp.ClientSession, *, force: bool = False) -> dict | None:
    """Proactive tip for the active curriculum step (not a plan readout)."""
    ensure_session_coach(sess)
    if sess.coach["phase"] != "teaching":
        return None
    project = get_project(sess.coach["project_id"])
    step = step_at(project, sess.coach["step_index"])
    if not step:
        return None
    key = f"step:{step['id']}:{sess.coach['step_index']}"
    if not force and sess.coach.get("last_tip_key") == key:
        return None
    twin = sess.twin or {}
    system = (
        "You are CURRENT, a calm electronics teacher at a breadboard. "
        "Start by saying what you SEE (observation / placements / hole letters), then "
        "give ONE concrete next wire action for Arduino Nano Blink. "
        "Do NOT recite the whole plan. Max 4 short sentences. Name pins D13 and GND correctly. "
        "If placements list breadboard holes (e.g. E12), mention whether they look right for this step."
    )
    user = json.dumps({
        "project": project["title"],
        "step": {
            "id": step["id"],
            "title": step["title"],
            "concept": step["concept"],
            "action": step["action"],
            "teach": step["teach"],
        },
        "twin": {
            "observation": twin.get("observation"),
            "components": twin.get("components"),
            "nets": twin.get("nets"),
            "placements": twin.get("placements"),
            "wiring_check": twin.get("wiring_check"),
        },
        "step_index": sess.coach["step_index"] + 1,
        "step_total": len(project["steps"]),
    })
    text, meta = await _wandb_chat(http, system, user)
    if not text:
        text = _fallback_tip(step)
        meta = {"ms": 0, "source": "curriculum", "model": None}
    sess.coach["last_tip_key"] = key
    return {
        "type": "guidance",
        "text": text,
        "finding_ids": [f"step_{step['id']}"],
        "source": meta.get("source"),
        "model": meta.get("model"),
        "ms": meta.get("ms"),
        "coach": public_coach_state(sess),
    }


async def converse(sess, http: aiohttp.ClientSession, question: str) -> dict:
    ensure_session_coach(sess)
    q = (question or "").strip()
    low = q.lower()

    # Project selection / demo path
    if sess.coach["phase"] == "ask_project":
        wants_blink = any(
            w in low
            for w in ("blink", "led", "arduino", "nano", "demo", "yes", "start", "build", "ok")
        )
        if wants_blink or not q:
            start_project(sess, "blink")
            tip = await teach_current_step(sess, http, force=True)
            opener = (
                "Great — Blink it is. Circuit: D13 → 220Ω → LED anode; cathode → GND. "
                "Arm the camera when the board is in frame."
            )
            text = opener + (" " + tip["text"] if tip else "")
            return {
                "type": "guidance",
                "text": text,
                "finding_ids": (tip or {}).get("finding_ids") or [],
                "source": (tip or {}).get("source") or "curriculum",
                "ms": (tip or {}).get("ms"),
                "coach": public_coach_state(sess),
            }
        return {
            "type": "guidance",
            "text": ask_project_opener(),
            "finding_ids": [],
            "source": "curriculum",
            "coach": public_coach_state(sess),
        }

    if any(w in low for w in ("next", "done", "finished", "continue", "got it", "ready")):
        st = advance_step(sess, 1)
        tip = await teach_current_step(sess, http, force=True)
        text = tip["text"] if tip else f"On to step {st['step_index'] + 1}."
        return {
            "type": "guidance",
            "text": text,
            "finding_ids": (tip or {}).get("finding_ids") or [],
            "source": (tip or {}).get("source") or "curriculum",
            "coach": st,
            "ms": (tip or {}).get("ms"),
        }

    if "back" in low or "previous" in low:
        st = advance_step(sess, -1)
        tip = await teach_current_step(sess, http, force=True)
        return {
            "type": "guidance",
            "text": tip["text"] if tip else "Stepped back.",
            "finding_ids": [],
            "source": "curriculum",
            "coach": st,
        }

    if any(w in low for w in ("before", "last time", "mistake", "history")):
        from history import search_my_mistakes
        ans = await search_my_mistakes(http, q)
        return {
            "type": "guidance",
            "text": ans.get("text") or "No prior session match in your VAST index yet.",
            "finding_ids": ["history"],
            "source": "vast",
            "evidence": ans.get("evidence"),
            "coach": public_coach_state(sess),
        }

    project = get_project(sess.coach.get("project_id") or "")
    step = step_at(project, sess.coach["step_index"]) if project else None
    system = (
        "You are CURRENT, a proactive electronics teacher. "
        "Answer the student's spoken question using the active Blink step and vision twin. "
        "Be concrete about pins and polarity. 2-4 short sentences. No full plan dump."
    )
    user = json.dumps({
        "question": q,
        "coach": public_coach_state(sess),
        "step": step,
        "twin": sess.twin,
    })
    text, meta = await _wandb_chat(http, system, user)
    if not text:
        if step:
            text = f"For {step['title']}: {step['action']}"
        else:
            text = "Ask a wiring question, or say “next” when that step is done."
        meta = {"source": "curriculum", "ms": 0}
    return {
        "type": "guidance",
        "text": text,
        "finding_ids": ["chat"],
        "source": meta.get("source"),
        "model": meta.get("model"),
        "ms": meta.get("ms"),
        "coach": public_coach_state(sess),
    }


async def on_twin_update(sess, http: aiohttp.ClientSession) -> dict | None:
    """After Cosmos twin: maybe nudge step progress + teach."""
    ensure_session_coach(sess)
    if sess.coach["phase"] != "teaching":
        # Stay quiet while still asking what to build — opener is sent on join
        return None
    project = get_project(sess.coach["project_id"])
    if not project:
        return None
    suggested = infer_step_from_twin(project, sess.twin)
    if suggested > sess.coach["step_index"] and suggested <= sess.coach["step_index"] + 1:
        sess.coach["step_index"] = suggested
        sess.coach["last_tip_key"] = None
    return await teach_current_step(sess, http, force=False)
